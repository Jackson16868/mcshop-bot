import os, certifi, json, re
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from flask import Flask, request, render_template_string, jsonify
from dotenv import load_dotenv
from datetime import datetime, timedelta, time as dtime
from models import db, User, Service, Order, OrderItem, Conversation, Vehicle, ShopSlot

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent

from flex_helper import reply_text, reply_flex
from flex_templates import (
    bubble_vehicle_picker, bubble_services_page,
    bubble_timeslots, bubble_confirm, bubble_orders,
    bubble_order_detail, carousel_orders_full,
    bubble_cancel_confirm, bubble_reschedule_picker,
    carousel_my_vehicles, bubble_settings,
    bubble_new_booking_picker,bubble_booking_success
)

load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_TOKEN  = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
handler = WebhookHandler(CHANNEL_SECRET)
configuration = Configuration(access_token=CHANNEL_TOKEN)

PLATE_RE = re.compile(r"^[A-Z0-9\-]{3,}$")

# ---------- Health ----------
@app.get("/healthz")
def healthz():
    return {"ok": True}

# ---------- LINE Callback (強化除錯) ----------
@app.post("/callback")
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        print("\n=== /callback ===")
        print("X-Line-Signature:", signature)
        print("Body preview:", body[:2000], "...\n")
        handler.handle(body, signature)
    except Exception:
        import traceback
        print("!! handler exception !!")
        traceback.print_exc()
        return "OK", 200
    return "OK", 200

# ---------- Helpers ----------
def get_or_create_user(line_user_id):
    u = User.query.filter_by(line_user_id=line_user_id).first()
    if not u:
        u = User(line_user_id=line_user_id)
        db.session.add(u)
        db.session.commit()
    return u

def get_or_create_conv(line_user_id):
    c = Conversation.query.filter_by(line_user_id=line_user_id).first()
    if not c:
        c = Conversation(line_user_id=line_user_id, state="idle", payload={})
        db.session.add(c)
        db.session.commit()
    if not isinstance(c.payload, dict):
        c.payload = {}
        db.session.commit()
    return c

def reset_conv(conv):
    conv.state = "idle"
    conv.payload = {}
    db.session.commit()

# NEW: 安全更新 JSON 欄位（避免原地修改不被 SQLAlchemy 偵測）
def set_payload(conv, **kwargs):
    p = dict(conv.payload or {})
    p.update(kwargs)
    conv.payload = p
    db.session.commit()
    return p

def _hydrate_payload_defaults_from_user(user, conv):
    """
    只在 payload 缺值時，帶入帳號的 name/phone，避免 Flex 空白。
    """
    p = dict(conv.payload or {})
    if not p.get("name") and user.name:
        p["name"] = user.name
    if not p.get("phone") and user.phone:
        p["phone"] = user.phone
    conv.payload = p
    db.session.commit()

def _sync_booking_display(conv):
    """
    統一提供 Flex 會讀取的鍵：
      - plate：車牌字串
      - service：服務名稱（同時保留 service_name）
      - time：顯示用預約時間字串（等於 booked_at）
      - name、phone：沿用 payload 值（若之前由 _hydrate 補過）
    """
    p = dict(conv.payload or {})

    # 補 plate（若已選車）
    if not p.get("plate") and p.get("vehicle_id"):
        v = Vehicle.query.get(p["vehicle_id"])
        if v and v.plate:
            p["plate"] = v.plate

    # service / service_name 對齊
    if p.get("service_name") and not p.get("service"):
        p["service"] = p["service_name"]

    # time 由 booked_at 映射
    if p.get("booked_at"):
        p["time"] = p["booked_at"]

    conv.payload = p
    db.session.commit()

def _safe_str(v):
    s = "" if v is None else str(v)
    s = s.strip()
    return s if s else "-"

def list_upcoming_orders(user_id, days_ahead=30, limit=5):
    now = datetime.now()
    q = (Order.query
         .filter(Order.user_id == user_id)
         .filter(Order.status.in_(["pending", "confirmed"]))
         .filter((Order.booked_at == None) | (Order.booked_at >= now))
         .order_by(Order.booked_at.asc().nullsfirst(), Order.id.desc())
         .limit(limit))
    return q.all()

def check_capacity(when: datetime) -> tuple[bool, str]:
    weekday = when.weekday()
    slots = (ShopSlot.query
             .filter(ShopSlot.weekday == weekday)
             .order_by(ShopSlot.start_time.asc())
             .all())
    if not slots:
        return False, "該日未開放預約（星期日休息），請選擇其他日期。"

    hm = dtime(when.hour, when.minute)
    chosen = None
    for s in slots:
        if s.start_time <= hm < s.end_time:
            chosen = s
            break
    if not chosen:
        return False, "所選時間不在營業時段（08:00–21:00）內，請重新選擇。"

    block_min = (when.minute // chosen.interval_min) * chosen.interval_min
    block_start = when.replace(minute=block_min, second=0, microsecond=0)
    block_end = block_start + timedelta(minutes=chosen.interval_min)

    cnt = (Order.query
           .filter(Order.status.in_(["pending", "confirmed"]))
           .filter(Order.booked_at >= block_start)
           .filter(Order.booked_at < block_end)
           .count())
    if cnt >= chosen.capacity:
        return False, "此時段名額已滿，請改其他時間。"
    return True, ""

def find_available_slots(start_dt: datetime, days: int = 14, max_per_day: int = 48):
    results = []
    end_dt = start_dt + timedelta(days=days)
    day_cursor = datetime(start_dt.year, start_dt.month, start_dt.day)

    while day_cursor < end_dt:
        weekday = day_cursor.weekday()
        day_slots = (ShopSlot.query
                     .filter(ShopSlot.weekday == weekday)
                     .order_by(ShopSlot.start_time.asc())
                     .all())
        per_day_count = 0

        for s in day_slots:
            cur = datetime.combine(day_cursor.date(), s.start_time)
            day_end = datetime.combine(day_cursor.date(), s.end_time)
            while cur < day_end and per_day_count < max_per_day:
                if cur >= start_dt:
                    ok, _ = check_capacity(cur)
                    if ok:
                        results.append(cur)
                        per_day_count += 1
                cur += timedelta(minutes=s.interval_min)

        day_cursor += timedelta(days=1)
        if len(results) >= 500:
            break
    return results

def make_order_rows(orders):
    rows = []
    for o in orders:
        t = o.booked_at.strftime("%Y-%m-%d %H:%M") if o.booked_at else "未排定"
        plate = "-"
        if getattr(o, "vehicle", None) and getattr(o.vehicle, "plate", None):
            plate = o.vehicle.plate

        svc_names = []
        try:
            for it in getattr(o, "items", []):
                if getattr(it, "service", None) and getattr(it.service, "name", None):
                    svc_names.append(it.service.name)
        except Exception:
            items = OrderItem.query.filter_by(order_id=o.id).all()
            svc_ids = [it.service_id for it in items if it.service_id]
            if svc_ids:
                svcs = Service.query.filter(Service.id.in_(svc_ids)).all()
                id2name = {s.id: s.name for s in svcs}
                for it in items:
                    name = id2name.get(it.service_id)
                    if name: svc_names.append(name)

        services = "、".join(svc_names) if svc_names else "-"
        rows.append({
            "id": o.id, "status": o.status, "time": t, "plate": plate, "services": services
        })
    return rows

# ---- DatetimePicker 安全邊界（避免 invalid date time order）----
def _datetimepicker_bounds(current=None, booked_at: datetime | None = None):
    now = current or datetime.now()
    min_dt = (now + timedelta(minutes=30)).replace(second=0, microsecond=0)
    max_dt = (now + timedelta(days=60)).replace(second=0, microsecond=0)
    if max_dt <= min_dt:
        max_dt = min_dt + timedelta(hours=1)

    initial_dt = booked_at.replace(second=0, microsecond=0) if booked_at else min_dt
    if initial_dt < min_dt:
        initial_dt = min_dt
    if initial_dt > max_dt:
        initial_dt = max_dt

    fmt = "%Y-%m-%dT%H:%M"
    return initial_dt.strftime(fmt), min_dt.strftime(fmt), max_dt.strftime(fmt)

# ---------- Admin ----------
from flask_admin import Admin, expose, BaseView
from flask_admin.contrib.sqla import ModelView
from flask_basicauth import BasicAuth
from wtforms.fields import DateTimeLocalField
from wtforms.validators import Optional as Opt
from flask_admin.model.form import InlineFormAdmin

app.config["BASIC_AUTH_USERNAME"] = os.getenv("ADMIN_USERNAME", "admin")
app.config["BASIC_AUTH_PASSWORD"] = os.getenv("ADMIN_PASSWORD", "changeme")
app.config["BASIC_AUTH_FORCE"] = False
basic_auth = BasicAuth(app)

class SecuredModelView(ModelView):
    def is_accessible(self): return True
    can_view_details = True
    page_size = 25
    column_display_pk = True

class UserAdmin(SecuredModelView):
    column_list = ("id", "line_user_id", "name", "phone", "created_at")
    column_searchable_list = ("line_user_id", "name", "phone")
    column_filters = ("created_at",)
    form_excluded_columns = ("orders", "vehicles")

class VehicleAdmin(SecuredModelView):
    column_list = ("id", "user_id", "plate", "brand", "model", "year", "created_at")
    column_searchable_list = ("plate", "brand", "model")
    column_filters = ("user_id", "brand", "model", "year", "created_at")

class ServiceAdmin(SecuredModelView):
    column_list = ("id", "name", "base_price", "duration_min", "recommend_days", "created_at")
    column_searchable_list = ("name",)
    column_filters = ("duration_min", "recommend_days", "created_at")

class OrderItemInline(InlineFormAdmin):
    form_columns = ("service", "qty", "unit_price", "subtotal")

class OrderAdmin(SecuredModelView):
    column_list = ("id", "user_id", "vehicle_id", "status", "booked_at", "created_at")
    column_searchable_list = ("status",)
    column_filters = ("status", "booked_at", "vehicle_id", "user_id", "created_at")
    column_default_sort = ("booked_at", True)
    inline_models = (OrderItemInline(OrderItem),)
    form_overrides = {"booked_at": DateTimeLocalField}
    form_args = {"booked_at": {"format": "%Y-%m-%dT%H:%M", "validators": [Opt()]}}
    def action_cancel(self, ids):
        count = 0
        for pk in ids:
            o = Order.query.get(pk)
            if o and o.status != "canceled":
                o.status = "canceled"; db.session.add(o); count += 1
        db.session.commit(); self.flash(f"已取消 {count} 筆預約", "success")
    def action_confirm(self, ids):
        count = 0
        for pk in ids:
            o = Order.query.get(pk)
            if o and o.status != "confirmed":
                o.status = "confirmed"; db.session.add(o); count += 1
        db.session.commit(); self.flash(f"已標記 {count} 筆為 confirmed", "success")
    action_disallowed_list = []
    def get_actions(self):
        actions = super().get_actions()
        actions["cancel"] = (self.action_cancel, "cancel", "取消選取的預約")
        actions["confirm"] = (self.action_confirm, "confirm", "將選取的預約標記為 confirmed")
        return actions

class OrderItemAdmin(SecuredModelView):
    column_list = ("id", "order_id", "service_id", "qty", "unit_price", "subtotal")
    column_filters = ("order_id", "service_id")

class ConversationAdmin(SecuredModelView):
    column_list = ("id", "line_user_id", "state", "updated_at")
    column_searchable_list = ("line_user_id", "state")
    column_filters = ("updated_at",)

class ShopSlotAdmin(SecuredModelView):
    column_list = ("id", "weekday", "start_time", "end_time", "interval_min", "capacity", "created_at")
    column_filters = ("weekday", "start_time", "end_time", "capacity", "created_at")
    form_columns = ("weekday", "start_time", "end_time", "interval_min", "capacity")

class CalendarView(BaseView):
    @expose("/")
    def index(self):
        html = """
        <!doctype html>
        <html>
          <head>
            <meta charset="utf-8">
            <title>預約日曆</title>
            <link href="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.10/index.global.min.css" rel="stylesheet">
          </head>
          <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans', 'Helvetica Neue', Arial;">
            <h2 style="margin:16px 24px;">預約日曆</h2>
            <div id="calendar" style="max-width:1100px;margin:0 auto 24px;"></div>
            <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.10/index.global.min.js"></script>
            <script>
              document.addEventListener("DOMContentLoaded", function() {
                var calendarEl = document.getElementById("calendar");
                var calendar = new FullCalendar.Calendar(calendarEl, {
                  initialView: "timeGridWeek",
                  nowIndicator: true,
                  slotMinTime: "08:00:00",
                  slotMaxTime: "21:00:00",
                  locale: "zh-tw",
                  firstDay: 1,
                  headerToolbar: { left: "prev,next today", center: "title", right: "dayGridMonth,timeGridWeek,timeGridDay" },
                  events: "/admin/api/events",
                  eventTimeFormat: { hour: "2-digit", minute: "2-digit", hour12: false },
                  displayEventEnd: true
                });
                calendar.render();
              });
            </script>
          </body>
        </html>
        """
        return render_template_string(html)

# 供 FullCalendar 取事件
@app.get("/admin/api/events")
def admin_events():
    start_str = request.args.get("start")
    end_str = request.args.get("end")
    try:
        start = datetime.fromisoformat(start_str.replace("Z", "+00:00")) if start_str else datetime.now() - timedelta(days=7)
        end = datetime.fromisoformat(end_str.replace("Z", "+00:00")) if end_str else datetime.now() + timedelta(days=30)
    except Exception:
        start = datetime.now() - timedelta(days=7)
        end = datetime.now() + timedelta(days=30)

    q = (Order.query
         .filter(Order.booked_at != None)
         .filter(Order.booked_at >= start)
         .filter(Order.booked_at <= end)
         .order_by(Order.booked_at.asc()))
    events = []
    for o in q.all():
        title = f"#{o.id} {o.status}"
        if getattr(o, "vehicle", None):
            title = f"#{o.id} {o.vehicle.plate} {o.status}"
        events.append({
            "id": o.id,
            "title": title,
            "start": o.booked_at.isoformat(),
            "end": (o.booked_at + timedelta(minutes=60)).isoformat(),
            "color": "#2E86C1" if o.status in ("pending", "confirmed") else "#999999",
            "url": f"/admin/order/edit/?id={o.id}"
        })
    return jsonify(events)

def setup_admin(app):
    admin = Admin(app, name="MCShop 後台", template_mode="bootstrap4", url="/admin")
    admin.add_view(UserAdmin(User, db.session, name="Users"))
    admin.add_view(VehicleAdmin(Vehicle, db.session, name="Vehicles"))
    admin.add_view(ServiceAdmin(Service, db.session, name="Services"))
    admin.add_view(OrderAdmin(Order, db.session, name="Orders"))
    admin.add_view(OrderItemAdmin(OrderItem, db.session, name="OrderItems"))
    admin.add_view(ConversationAdmin(Conversation, db.session, name="Conversations"))
    admin.add_view(ShopSlotAdmin(ShopSlot, db.session, name="ShopSlots"))
    admin.add_view(CalendarView(name="Calendar", endpoint="calendar"))
    return admin

@app.before_request
def protect_admin():
    if request.path.startswith("/admin"):
        if not basic_auth.authenticate():
            return basic_auth.challenge()

# ========== 文字事件 ==========
@handler.add(MessageEvent, message=TextMessageContent)
def on_text(event):
    try:
        text = (event.message.text or "").strip()
        print(f"[on_text] user:{event.source.user_id} text:{text}")
        user = get_or_create_user(event.source.user_id)
        conv  = get_or_create_conv(event.source.user_id)

        # 先把帳號姓名/電話灌入缺值欄位，再同步 Flex 需要的鍵
        _hydrate_payload_defaults_from_user(user, conv)
        _sync_booking_display(conv)

        with ApiClient(configuration) as api_client:
            # 通用取消（純文字）
            if text in ["取消", "cancel"]:
                reset_conv(conv)
                return reply_text(api_client, event.reply_token, "已取消流程 ✅\n需要預約請輸入「預約」。")

            # 文字快速指令（相容舊 message 按鈕）
            m = re.match(r"^取消預約\s*#?(\d+)$", text)
            if m:
                oid = int(m.group(1))
                o = Order.query.filter_by(id=oid, user_id=user.id).first()
                if not o: return reply_text(api_client, event.reply_token, "找不到這筆預約或不屬於你。")
                row = make_order_rows([o])[0]
                conv.state = "cancel_confirm_flex"; conv.payload = {"order_id": oid}; db.session.commit()
                return reply_flex(api_client, event.reply_token, "確認取消", bubble_cancel_confirm(row))

            m = re.match(r"^確認取消\s*#?(\d+)$", text)
            if m:
                oid = int(m.group(1))
                o = Order.query.filter_by(id=oid, user_id=user.id).first()
                if not o: return reply_text(api_client, event.reply_token, "找不到這筆預約或不屬於你。")
                if o.status != "canceled":
                    o.status = "canceled"; db.session.add(o); db.session.commit()
                reset_conv(conv)
                when = o.booked_at.strftime("%Y-%m-%d %H:%M") if o.booked_at else "未排定"
                return reply_text(api_client, event.reply_token, f"✅ 已取消 #{o.id}｜{when}")

            m = re.match(r"^調整時間\s*#?(\d+)$", text)
            if m:
                oid = int(m.group(1))
                o = Order.query.filter_by(id=oid, user_id=user.id).first()
                if not o: return reply_text(api_client, event.reply_token, "找不到這筆預約或不屬於你。")
                row = make_order_rows([o])[0]
                initial_iso, min_iso, max_iso = _datetimepicker_bounds(booked_at=o.booked_at)
                conv.state = "reschedule_wait_pick"; set_payload(conv, order_id=oid)
                return reply_flex(api_client, event.reply_token, "選擇新的日期時間",
                                  bubble_reschedule_picker(row, initial_iso, min_iso, max_iso))

            # 入口：開始預約
            if text in ["預約","預約維修","預約保養"]:
                conv.state = "ask_name"; conv.payload = {}; db.session.commit()
                _hydrate_payload_defaults_from_user(user, conv)
                _sync_booking_display(conv)
                return reply_text(api_client, event.reply_token, "請輸入您的姓名：")

            # 表單：姓名/電話
            if conv.state == "ask_name":
                set_payload(conv, name=(text.strip() or user.name or ""))
                _sync_booking_display(conv)
                conv.state = "ask_phone"; db.session.commit()
                return reply_text(api_client, event.reply_token, "請輸入您的電話（09xxxxxxxx）：")

            if conv.state == "ask_phone":
                if not text.isdigit() or len(text) < 8:
                    return reply_text(api_client, event.reply_token, "電話格式不太對，請再輸入一次（例：0912345678）")
                set_payload(conv, phone=text.strip())
                _sync_booking_display(conv)

                # 選車
                vehicles = Vehicle.query.filter_by(user_id=user.id).order_by(Vehicle.created_at.desc()).all()
                if not vehicles:
                    conv.state="v_add_plate"; db.session.commit()
                    return reply_text(api_client, event.reply_token, "目前沒有綁定車輛，請輸入車牌（例：ABC-1234）")
                elif len(vehicles)==1:
                    v = vehicles[0]
                    set_payload(conv, vehicle_id=v.id, plate=v.plate, svc_page=1)
                    conv.state="svc_page"; db.session.commit()
                    _sync_booking_display(conv)
                    svc = [{"name": s.name, "mins": (s.duration_min or 30)} for s in Service.query.order_by(Service.name).all()]
                    return reply_flex(api_client, event.reply_token, "請選擇服務", bubble_services_page(svc, 1))
                else:
                    opts = [{"i":i+1,"label":f"{v.plate} {v.brand or ''} {v.model or ''}".strip(),"id":v.id}
                            for i,v in enumerate(vehicles)]
                    set_payload(conv, vehicle_opts=opts)
                    conv.state = "choose_vehicle"; db.session.commit()
                    _sync_booking_display(conv)
                    return reply_flex(api_client, event.reply_token, "請選擇車輛", bubble_vehicle_picker(opts))

            # 新增車牌
            if conv.state == "v_add_plate":
                plate = text.upper().strip()
                if not PLATE_RE.match(plate):
                    return reply_text(api_client, event.reply_token, "車牌格式不符，請再輸入（例：ABC-1234）")
                v = Vehicle(user_id=user.id, plate=plate); db.session.add(v); db.session.commit()
                set_payload(conv, vehicle_id=v.id, plate=v.plate, svc_page=1)
                conv.state="svc_page"; db.session.commit()
                _sync_booking_display(conv)
                svc = [{"name": s.name, "mins": (s.duration_min or 30)} for s in Service.query.order_by(Service.name).all()]
                return reply_flex(api_client, event.reply_token, "請選擇服務", bubble_services_page(svc, 1))

            # 我的車輛（Flex）
            if text in ["我的車輛","車輛","車子"]:
                vehicles = (Vehicle.query
                            .filter_by(user_id=user.id)
                            .order_by(Vehicle.created_at.desc())
                            .all())
                vrows = [{"id":v.id,"plate":v.plate,"brand":v.brand,"model":v.model} for v in vehicles]
                return reply_flex(api_client, event.reply_token, "我的車輛", carousel_my_vehicles(vrows))

            # 設定（Flex）
            if text in ["設定","設定資料","會員設定","帳戶設定"]:
                return reply_flex(api_client, event.reply_token, "設定", bubble_settings(user))

            # 接收設定修改（姓名/電話）
            if conv.state == "edit_name":
                user.name = text.strip()
                db.session.add(user); db.session.commit()
                reset_conv(conv)
                return reply_text(api_client, event.reply_token, f"已更新姓名為：{_safe_str(user.name)} ✅")

            if conv.state == "edit_phone":
                if not text.isdigit() or len(text) < 8:
                    return reply_text(api_client, event.reply_token, "電話格式不太對，請再輸入一次（例：0912345678）")
                user.phone = text.strip()
                db.session.add(user); db.session.commit()
                reset_conv(conv)
                return reply_text(api_client, event.reply_token, f"已更新電話為：{_safe_str(user.phone)} ✅")

            # 查詢我的預約（Carousel，含取消/調整）
            if text in ["我的預約","查詢預約"]:
                orders = (Order.query
                          .filter(Order.user_id == user.id)
                          .filter(Order.status.in_(["pending","confirmed"]))
                          .order_by(Order.booked_at.asc().nullsfirst(), Order.id.desc())
                          .limit(10).all())
                if not orders:
                    return reply_text(api_client, event.reply_token, "目前沒有預約紀錄。輸入「預約」可以開始預約。")
                rows = make_order_rows(orders)
                return reply_flex(api_client, event.reply_token, "我的預約列表", carousel_orders_full(rows))

            # 預設
            return reply_text(api_client, event.reply_token, "輸入「預約」開始預約（Flex 選單）")

    except Exception:
        import traceback
        traceback.print_exc()
        try:
            with ApiClient(configuration) as api_client:
                return reply_text(api_client, event.reply_token, "系統忙線或設定有誤，請稍後再試 🙏")
        except Exception:
            pass

# ========== Postback 事件 ==========
@handler.add(PostbackEvent)
def on_postback(event):
    try:
        data = (getattr(event.postback, "data", "") or "").strip()
        params = getattr(event.postback, "params", {}) or {}
        print(f"[on_postback] data={data} params={params}")
        user = get_or_create_user(event.source.user_id)
        conv  = get_or_create_conv(event.source.user_id)

        # 進任何 Postback 前，補 name/phone 並同步顯示鍵
        _hydrate_payload_defaults_from_user(user, conv)
        _sync_booking_display(conv)

        with ApiClient(configuration) as api_client:

            # 設定：修改姓名 / 電話 / 我的車輛（入口）
            if data == "SETTINGS_EDIT_NAME":
                conv.state = "edit_name"; conv.payload = {}; db.session.commit()
                _hydrate_payload_defaults_from_user(user, conv); _sync_booking_display(conv)
                return reply_text(api_client, event.reply_token, "請輸入新姓名：")

            if data == "SETTINGS_EDIT_PHONE":
                conv.state = "edit_phone"; conv.payload = {}; db.session.commit()
                _hydrate_payload_defaults_from_user(user, conv); _sync_booking_display(conv)
                return reply_text(api_client, event.reply_token, "請輸入新電話（09xxxxxxxx）：")

            if data == "MY_VEHICLES":
                vehicles = (Vehicle.query
                            .filter_by(user_id=user.id)
                            .order_by(Vehicle.created_at.desc())
                            .all())
                vrows = [{"id":v.id,"plate":v.plate,"brand":v.brand,"model":v.model} for v in vehicles]
                return reply_flex(api_client, event.reply_token, "我的車輛", carousel_my_vehicles(vrows))

            # 車輛選擇 / 使用
            if data == "VEHICLE_ADD":
                conv.state="v_add_plate"; db.session.commit()
                return reply_text(api_client, event.reply_token, "請輸入新車牌（例：ABC-1234）：")

            m = re.match(r"^VEHICLE_PICK:(\d+)$", data)
            if m:
                idx = int(m.group(1))
                opts = conv.payload.get("vehicle_opts", [])
                chosen = next((o for o in opts if o["i"]==idx), None)
                if not chosen:
                    return reply_text(api_client, event.reply_token, "序號不在清單中，請重新選擇。")
                plate_label = chosen["label"].split()[0] if chosen["label"] else "-"
                set_payload(conv, vehicle_id=chosen["id"], plate=plate_label, svc_page=1)
                conv.state="svc_page"; db.session.commit()
                _sync_booking_display(conv)
                svc = [{"name": s.name, "mins": (s.duration_min or 30)} for s in Service.query.order_by(Service.name).all()]
                return reply_flex(api_client, event.reply_token, "請選擇服務", bubble_services_page(svc, 1))

            m = re.match(r"^VEHICLE_USE:(\d+)$", data)
            if m:
                vid = int(m.group(1))
                v = Vehicle.query.filter_by(id=vid, user_id=user.id).first()
                if not v:
                    return reply_text(api_client, event.reply_token, "找不到這台車或不屬於你。")
                set_payload(conv, vehicle_id=v.id, plate=v.plate, svc_page=1)
                conv.state="svc_page"; db.session.commit()
                _sync_booking_display(conv)
                svc = [{"name": s.name, "mins": (s.duration_min or 30)} for s in Service.query.order_by(Service.name).all()]
                return reply_flex(api_client, event.reply_token, "請選擇服務", bubble_services_page(svc, 1))

            # 服務分頁 / 選擇
            if data == "SVC_PREV" or data == "SVC_NEXT":
                svc = [{"name": s.name, "mins": (s.duration_min or 30)} for s in Service.query.order_by(Service.name).all()]
                page = conv.payload.get("svc_page", 1) or 1
                page = max(1, page-1) if data == "SVC_PREV" else page+1
                set_payload(conv, svc_page=page)
                _sync_booking_display(conv)
                return reply_flex(api_client, event.reply_token, "請選擇服務", bubble_services_page(svc, page))

            m = re.match(r"^SVC_PICK:(.+)$", data)
            if m:
                name = m.group(1)
                s = Service.query.filter(Service.name==name).first()
                if not s:
                    return reply_text(api_client, event.reply_token, "找不到此服務，請重新選擇。")

                # 存入所選服務（同時寫 service 與 service_name）
                set_payload(conv, service_id=s.id, service_name=s.name, service=s.name)

                # datetimepicker（新預約）
                initial_iso, min_iso, max_iso = _datetimepicker_bounds(booked_at=None)
                conv.state = "new_booking_pick"
                db.session.commit()
                _sync_booking_display(conv)

                return reply_flex(
                    api_client, event.reply_token, "選擇預約時間",
                    bubble_new_booking_picker(conv.payload, initial_iso, min_iso, max_iso)
                )

            # （保留）清單式時段分頁 / 選擇
            if data in ["SLOT_PREV","SLOT_NEXT"]:
                slots = [datetime.strptime(s, "%Y-%m-%d %H:%M") for s in conv.payload.get("slots_cache", [])]
                page  = conv.payload.get("slot_page", 1) or 1
                page = max(1, page-1) if data == "SLOT_PREV" else page+1
                set_payload(conv, slot_page=page)
                _sync_booking_display(conv)
                return reply_flex(api_client, event.reply_token, "請選擇時段", bubble_timeslots(slots, page))

            m = re.match(r"^SLOT_PICK:(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2})$", data)
            if m:
                ts = m.group(1)
                when = datetime.strptime(ts, "%Y-%m-%d %H:%M")
                ok,msg = check_capacity(when)
                if not ok:
                    return reply_text(api_client, event.reply_token, msg)
                set_payload(conv, booked_at=when.strftime("%Y-%m-%d %H:%M"))
                conv.state = "confirm"; db.session.commit()
                _sync_booking_display(conv)
                return reply_flex(api_client, event.reply_token, "請確認預約資訊", bubble_confirm(conv.payload))

            # 確認/取消整個預約流程
            if data == "CONFIRM_SUBMIT":
                _sync_booking_display(conv)
                p = conv.payload or {}

                # 防呆：必須有時間
                if not p.get("booked_at"):
                    return reply_text(api_client, event.reply_token, "請先選擇預約時間喔 🙏")

                # 若尚未輸入姓名/電話但帳號有資料，補齊
                if not p.get("name") and user.name:
                    p["name"] = user.name
                if not p.get("phone") and user.phone:
                    p["phone"] = user.phone
                conv.payload = p; db.session.commit()

                user.name = p.get("name") or user.name
                user.phone = p.get("phone") or user.phone
                db.session.add(user); db.session.commit()

                when = datetime.strptime(p["booked_at"], "%Y-%m-%d %H:%M")
                order = Order(
                    user_id=user.id,
                    vehicle_id=p.get("vehicle_id"),
                    status="pending",
                    booked_at=when,
                    note=f"車牌:{p.get('plate')}"
                )
                db.session.add(order); db.session.commit()
                item = OrderItem(order_id=order.id, service_id=p.get("service_id"), qty=1, unit_price=0, subtotal=0)
                db.session.add(item); db.session.commit()
                reset_conv(conv)
                return reply_flex(api_client, event.reply_token, "預約成功",
                                 bubble_booking_success(order.id, p))


            if data == "FLOW_CANCEL":
                reset_conv(conv)
                return reply_text(api_client, event.reply_token, "已取消流程 ✅\n需要預約請輸入「預約」。")

            # 我的預約：取消/改期
            m = re.match(r"^CANCEL#(\d+)$", data)
            if m:
                oid = int(m.group(1))
                o = Order.query.filter_by(id=oid, user_id=user.id).first()
                if not o:
                    return reply_text(api_client, event.reply_token, "查無此預約。")
                row = make_order_rows([o])[0]
                conv.state = "cancel_confirm_flex"; set_payload(conv, order_id=oid)
                return reply_flex(api_client, event.reply_token, "確認取消", bubble_cancel_confirm(row))

            m = re.match(r"^CANCEL_CONFIRM#(\d+)$", data)
            if m:
                oid = int(m.group(1))
                o = Order.query.filter_by(id=oid, user_id=user.id).first()
                if not o:
                    return reply_text(api_client, event.reply_token, "查無此預約。")
                o.status = "canceled"; db.session.add(o); db.session.commit()
                when = o.booked_at.strftime("%Y-%m-%d %H:%M") if o.booked_at else "未排定"
                reset_conv(conv)
                return reply_text(api_client, event.reply_token, f"✅ 已取消 #{o.id}｜{when}")

            if data == "BACK_MY_ORDERS":
                orders = (Order.query
                          .filter(Order.user_id == user.id)
                          .filter(Order.status.in_(["pending","confirmed"]))
                          .order_by(Order.booked_at.asc().nullsfirst(), Order.id.desc())
                          .limit(10).all())
                if not orders:
                    return reply_text(api_client, event.reply_token, "目前沒有預約紀錄。輸入「預約」可以開始預約。")
                rows = make_order_rows(orders)
                return reply_flex(api_client, event.reply_token, "我的預約列表", carousel_orders_full(rows))

            # 新預約：datetimepicker 回傳（data = NEWBOOK）
            if data == "NEWBOOK" and ("datetime" in params or "date" in params or "time" in params):
                picked = params.get("datetime") or params.get("date") or params.get("time")
                when = datetime.strptime(picked, "%Y-%m-%dT%H:%M")

                ok, msg = check_capacity(when)
                if not ok:
                    return reply_text(api_client, event.reply_token, msg)

                # 存入時間，進入確認頁
                set_payload(conv, booked_at=when.strftime("%Y-%m-%d %H:%M"))
                conv.state = "confirm"
                db.session.commit()
                _sync_booking_display(conv)

                return reply_flex(api_client, event.reply_token, "請確認預約資訊", bubble_confirm(conv.payload))

            # 改期：顯示 datetimepicker
            m = re.match(r"^RESCHEDULE#(\d+)$", data)
            if m and not params:
                oid = int(m.group(1))
                o = Order.query.filter_by(id=oid, user_id=user.id).first()
                if not o:
                    return reply_text(api_client, event.reply_token, "查無此預約。")
                row = make_order_rows([o])[0]
                initial_iso, min_iso, max_iso = _datetimepicker_bounds(booked_at=o.booked_at)
                conv.state = "reschedule_wait_pick"; set_payload(conv, order_id=oid)
                return reply_flex(api_client, event.reply_token, "選擇新的日期時間",
                                  bubble_reschedule_picker(row, initial_iso, min_iso, max_iso))

            # 改期：picker 回傳
            if data.startswith("RESCHEDULE#") and ("datetime" in params or "date" in params or "time" in params):
                oid = int(data.split("#",1)[1])
                picked = params.get("datetime") or params.get("date") or params.get("time")
                when = datetime.strptime(picked, "%Y-%m-%dT%H:%M")
                ok, msg = check_capacity(when)
                if not ok:
                    return reply_text(api_client, event.reply_token, msg)
                o = Order.query.filter_by(id=oid, user_id=user.id).first()
                if not o:
                    return reply_text(api_client, event.reply_token, "查無此預約。")
                o.booked_at = when
                if o.status == "pending":
                    o.status = "confirmed"
                db.session.add(o); db.session.commit()
                reset_conv(conv)
                return reply_text(api_client, event.reply_token, f"✅ 已改期：#{o.id} → {when:%Y-%m-%d %H:%M}")

            return "OK"

    except Exception:
        import traceback
        traceback.print_exc()
        return "OK"

# ---------- Boot ----------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        if Service.query.count() == 0:
            db.session.add_all([
                Service(name="更換機油", base_price=400, duration_min=20, recommend_days=90),
                Service(name="更換齒輪油", base_price=200, duration_min=15, recommend_days=180),
                Service(name="一般保養檢查", base_price=0, duration_min=30, recommend_days=180),
                Service(name="煞車皮更換", base_price=600, duration_min=40, recommend_days=365),
            ])
            db.session.commit()
        if ShopSlot.query.count() == 0:
            # 週一~週六 08:00-21:00，30 分鐘一格，每格容量 2；週日(6)休息
            for wd in range(0, 6):  # 0=Mon ... 5=Sat
                db.session.add(ShopSlot(
                    weekday=wd,
                    start_time=dtime(8, 0),
                    end_time=dtime(21, 0),
                    interval_min=30,
                    capacity=2
                ))
            db.session.commit()

        setup_admin(app)
    app.run(port=5001)
