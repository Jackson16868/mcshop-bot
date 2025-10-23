import os, certifi, json, re
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from flask import Flask, request, abort, render_template_string, jsonify
from dotenv import load_dotenv
from datetime import datetime, timedelta, time as dtime
from models import db, User, Service, Order, OrderItem, Conversation, Vehicle, ShopSlot
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# Admin / Auth
from flask_admin import Admin, expose, BaseView
from flask_admin.contrib.sqla import ModelView
from flask_basicauth import BasicAuth
from wtforms.fields import DateTimeLocalField
from wtforms.validators import Optional as Opt
from flask_admin.model.form import InlineFormAdmin

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

# ---------- LINE Callback ----------
@app.post("/callback")
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        abort(400, str(e))
    return "OK"

# ---------- Helpers ----------
def _reply(token, text):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message_with_http_info(
            ReplyMessageRequest(reply_token=token, messages=[TextMessage(text=text)])
        )

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

def services_text():
    rows = Service.query.order_by(Service.name).all()
    if not rows:
        return "目前尚未設定可預約的服務，請稍後再試。"
    return "請回覆需要的服務：\n" + "\n".join([f"- {s.name}（約{(s.duration_min or 30)} 分鐘）" for s in rows])

def list_upcoming_orders(user_id, days_ahead=30, limit=5):
    now = datetime.now()
    q = (Order.query
         .filter(Order.user_id == user_id)
         .filter(Order.status.in_(["pending", "confirmed"]))
         .filter((Order.booked_at == None) | (Order.booked_at >= now))
         .order_by(Order.booked_at.asc().nullsfirst(), Order.id.desc())
         .limit(limit))
    return q.all()

def render_order_lines(rows):
    lines = []
    for i, o in enumerate(rows, start=1):
        t = o.booked_at.strftime("%Y-%m-%d %H:%M") if o.booked_at else "未排定"
        plate = ""
        if getattr(o, "vehicle", None):
            plate = f"｜{o.vehicle.plate}"
        lines.append(f"{i}. #{o.id}{plate}｜{t}｜{o.status}")
    return lines

# ---------- Slot Capacity Check ----------
def check_capacity(when: datetime) -> tuple[bool, str]:
    weekday = when.weekday()  # 0=Mon .. 6=Sun
    slots = (ShopSlot.query
             .filter(ShopSlot.weekday == weekday)
             .order_by(ShopSlot.start_time.asc())
             .all())
    if not slots:
        return False, "該日未開放預約，請選擇營業日。"

    hm = dtime(when.hour, when.minute)
    chosen = None
    for s in slots:
        if s.start_time <= hm < s.end_time:
            chosen = s
            break
    if not chosen:
        return False, "所選時間不在營業時段內，請重新輸入。"

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

# ---------- LINE Text Handler ----------
@handler.add(MessageEvent, message=TextMessageContent)
def on_text(event: MessageEvent):
    text = (event.message.text or "").strip()
    line_user_id = event.source.user_id
    user = get_or_create_user(line_user_id)
    conv = get_or_create_conv(line_user_id)

    # 通用指令
    if text in ["取消", "cancel"]:
        reset_conv(conv)
        _reply(event.reply_token, "已取消流程 ✅\n需要預約請輸入「預約」。")
        return

    # 主選單
    if text in ["預約", "預約維修", "預約保養"]:
        conv.state = "ask_name"
        conv.payload = {}
        db.session.commit()
        _reply(event.reply_token, "請輸入您的姓名：\n（隨時輸入「取消」可中止）")
        return

    if text in ["我的預約", "查詢預約"]:
        orders = Order.query.filter_by(user_id=user.id).order_by(Order.id.desc()).limit(5).all()
        if not orders:
            _reply(event.reply_token, "目前沒有預約紀錄。輸入「預約」可以開始預約。")
        else:
            msg = "最近預約：\n" + "\n".join(
                [f"- #{o.id} 狀態:{o.status} 時間:{o.booked_at.strftime('%Y-%m-%d %H:%M') if o.booked_at else '未排定'}"
                 for o in orders]
            )
            _reply(event.reply_token, msg + "\n\n你也可以輸入「取消預約」或「調整時間」。")
        return

    # 取消 / 改期 入口
    if text in ["取消預約", "我要取消預約"]:
        rows = list_upcoming_orders(user.id)
        if not rows:
            _reply(event.reply_token, "目前沒有可取消的預約。若需要協助請輸入「預約」。")
            return
        conv.payload = {"action": "cancel", "orders": [o.id for o in rows]}
        conv.state = "choose_order_action"
        db.session.commit()
        _reply(event.reply_token, "請選擇要取消的預約（輸入序號）：\n" + "\n".join(render_order_lines(rows)))
        return

    if text in ["調整時間", "更改時間", "改時間", "變更時間"]:
        rows = list_upcoming_orders(user.id)
        if not rows:
            _reply(event.reply_token, "目前沒有可調整的預約。若需要協助請輸入「預約」。")
            return
        conv.payload = {"action": "reschedule", "orders": [o.id for o in rows]}
        conv.state = "choose_order_action"
        db.session.commit()
        _reply(event.reply_token, "請選擇要調整的預約（輸入序號）：\n" + "\n".join(render_order_lines(rows)))
        return

    if conv.state == "choose_order_action":
        try:
            n = int(text)
        except ValueError:
            _reply(event.reply_token, "格式不正確，請輸入清單中的序號（例如：1）。")
            return
        ids = conv.payload.get("orders") or []
        if n < 1 or n > len(ids):
            _reply(event.reply_token, "序號不在清單中，請重新輸入（例如：1）。")
            return
        order_id = ids[n-1]
        conv.payload = {**conv.payload, "order_id": order_id}
        action = conv.payload.get("action")
        if action == "cancel":
            conv.state = "cancel_confirm"
            db.session.commit()
            _reply(event.reply_token, f"確定要取消訂單 #{order_id} 嗎？（回覆「確認」取消 / 其它字放棄）")
            return
        elif action == "reschedule":
            conv.state = "reschedule_ask_time"
            db.session.commit()
            _reply(event.reply_token, "請輸入新的時間（格式：YYYY-MM-DD HH:MM，例如 2025-10-20 14:30）：")
            return
        reset_conv(conv)
        _reply(event.reply_token, "動作有誤，請重新輸入。")
        return

    if conv.state == "cancel_confirm":
        if text in ["確認", "ok", "OK", "是"]:
            order_id = conv.payload.get("order_id")
            o = Order.query.filter_by(id=order_id, user_id=user.id).first()
            if not o:
                reset_conv(conv); _reply(event.reply_token, "找不到這筆預約，請再試一次。"); return
            o.status = "canceled"
            db.session.add(o); db.session.commit()
            reset_conv(conv)
            when = o.booked_at.strftime("%Y-%m-%d %H:%M") if o.booked_at else "未排定"
            _reply(event.reply_token, f"已為你取消預約 ✅\n#{o.id}｜{when}")
            return
        reset_conv(conv); _reply(event.reply_token, "已放棄取消。"); return

    if conv.state == "reschedule_ask_time":
        try:
            when = datetime.strptime(text, "%Y-%m-%d %H:%M")
        except ValueError:
            _reply(event.reply_token, "時間格式不正確，請用 YYYY-MM-DD HH:MM（例 2025-10-20 14:30）"); return
        ok, msg = check_capacity(when)
        if not ok:
            _reply(event.reply_token, msg); return
        order_id = conv.payload.get("order_id")
        o = Order.query.filter_by(id=order_id, user_id=user.id).first()
        if not o:
            reset_conv(conv); _reply(event.reply_token, "找不到這筆預約，請再試一次。"); return
        o.booked_at = when
        if o.status == "pending":
            o.status = "confirmed"
        db.session.add(o); db.session.commit()
        reset_conv(conv)
        _reply(event.reply_token, f"✅ 已為你改期：\n#{o.id} 新時間 {when:%Y-%m-%d %H:%M}")
        return

    # 車輛與預約
    if text in ["我的車輛", "車輛"]:
        vehicles = Vehicle.query.filter_by(user_id=user.id).order_by(Vehicle.created_at.desc()).all()
        if not vehicles:
            conv.state = "v_add_plate"; conv.payload = {}; db.session.commit()
            _reply(event.reply_token, "目前沒有綁定車輛。\n請輸入車牌新增（例：ABC-1234）\n（隨時輸入「取消」可中止）")
        else:
            lines = [f"- {v.plate}｜{(v.brand or '')} {(v.model or '')}".strip() for v in vehicles]
            lines.append("\n若要新增，輸入「新增車輛」")
            _reply(event.reply_token, "你的車輛：\n" + "\n".join(lines))
        return

    if text in ["新增車輛", "新增 車輛"]:
        conv.state = "v_add_plate"; conv.payload = {}; db.session.commit()
        _reply(event.reply_token, "請輸入車牌（例：ABC-1234）")
        return

    if text in ["設定", "設定資料"]:
        conv.state = "settings_menu"; conv.payload = {}; db.session.commit()
        _reply(event.reply_token,
               "想設定哪一項？\n- 回覆「設定-姓名」更新姓名\n- 回覆「設定-手機」更新電話\n- 回覆「設定-車牌」更新常用車牌\n（隨時輸入「取消」可中止）")
        return

    if text == "設定-姓名":
        conv.state = "set_name"; db.session.commit(); _reply(event.reply_token, "請輸入新的姓名："); return
    if text == "設定-手機":
        conv.state = "set_phone"; db.session.commit(); _reply(event.reply_token, "請輸入新的手機（例：0912345678）："); return
    if text == "設定-車牌":
        conv.state = "set_plate"; db.session.commit(); _reply(event.reply_token, "請輸入常用車牌（例：ABC-1234）："); return

    if conv.state == "set_name":
        user.name = text; db.session.add(user); db.session.commit()
        reset_conv(conv); _reply(event.reply_token, f"已更新姓名為：{user.name} ✅"); return
    if conv.state == "set_phone":
        if not text.isdigit() or len(text) < 8:
            _reply(event.reply_token, "電話格式不太對，請再輸入一次（例：0912345678）"); return
        user.phone = text; db.session.add(user); db.session.commit()
        reset_conv(conv); _reply(event.reply_token, f"已更新手機為：{user.phone} ✅"); return
    if conv.state == "set_plate":
        note = (user.note or "").strip()
        tag = f"常用車牌:{text.upper()}"
        if tag not in note:
            note = (note + " " + tag).strip()
        user.note = note; db.session.add(user); db.session.commit()
        reset_conv(conv); _reply(event.reply_token, f"已設定常用車牌：{text.upper()} ✅"); return

    # 車輛新增流程
    if conv.state == "v_add_plate":
        plate = text.upper().replace(" ", "")
        if not PLATE_RE.match(plate):
            _reply(event.reply_token, "車牌格式不太對，請再輸入一次（例：ABC-1234）"); return
        exists = Vehicle.query.filter_by(user_id=user.id, plate=plate).first()
        if exists:
            reset_conv(conv); _reply(event.reply_token, f"此車牌已存在：{plate} ✅\n輸入「我的車輛」查看清單。"); return
        conv.payload = {"plate": plate}; conv.state = "v_add_brand"; db.session.commit()
        _reply(event.reply_token, "請輸入品牌（例：Yamaha / Kymco / SYM）："); return

    if conv.state == "v_add_brand":
        conv.payload = {**conv.payload, "brand": text.strip()}
        conv.state = "v_add_model"; db.session.commit()
        _reply(event.reply_token, "請輸入車型（例：Many 110 / JET SL / BWS）："); return

    if conv.state == "v_add_model":
        p = conv.payload
        vehicle = Vehicle(user_id=user.id, plate=p["plate"], brand=p.get("brand"), model=text.strip())
        db.session.add(vehicle); db.session.commit()
        if conv.payload.get("_booking_flow") == True:
            conv.payload = {**conv.payload, "vehicle_id": vehicle.id, "plate": vehicle.plate}
            conv.state = "ask_service"; db.session.commit()
            _reply(event.reply_token, "已新增並選擇此車輛 ✅\n" + services_text()); return
        reset_conv(conv)
        _reply(event.reply_token, f"✅ 已新增車輛：{vehicle.plate}\n品牌/車型：{vehicle.brand or ''} {vehicle.model or ''}\n輸入「我的車輛」可查看清單。")
        return

    # 預約主流程
    if conv.state == "ask_name":
        conv.payload = {**conv.payload, "name": text}
        conv.state = "ask_phone"; db.session.commit()
        _reply(event.reply_token, "請輸入您的電話（09xxxxxxxx）："); return

    if conv.state == "ask_phone":
        if not text.isdigit() or len(text) < 8:
            _reply(event.reply_token, "電話格式不太對，請再輸入一次（例：0912345678）"); return
        conv.payload = {**conv.payload, "phone": text}
        vehicles = Vehicle.query.filter_by(user_id=user.id).order_by(Vehicle.created_at.desc()).all()
        if len(vehicles) == 0:
            conv.state = "ask_plate"; db.session.commit()
            _reply(event.reply_token, "請輸入車牌（例：ABC-1234）。\n（之後會自動幫你建立車輛資料）"); return
        elif len(vehicles) == 1:
            v = vehicles[0]
            conv.payload = {**conv.payload, "vehicle_id": v.id, "plate": v.plate}
            conv.state = "ask_service"; db.session.commit()
            _reply(event.reply_token, f"已選擇你的車輛：{v.plate}（{(v.brand or '')} {(v.model or '')}）\n" + services_text()); return
        else:
            options = [{"i": i+1, "id": v.id, "plate": v.plate, "brand": v.brand or "", "model": v.model or ""} for i, v in enumerate(vehicles)]
            conv.payload = {**conv.payload, "vehicle_options": options}
            conv.state = "choose_vehicle"; db.session.commit()
            lines = [f"{opt['i']}. {opt['plate']}｜{opt['brand']} {opt['model']}".strip() for opt in options]
            lines.append("請輸入序號（例如：1），或輸入「新增」新增新車輛。")
            _reply(event.reply_token, "請選擇車輛：\n" + "\n".join(lines)); return

    if conv.state == "choose_vehicle":
        if text in ["新增", "新增車輛"]:
            conv.payload = {**conv.payload, "_booking_flow": True}
            conv.state = "v_add_plate"; db.session.commit()
            _reply(event.reply_token, "請輸入新車牌（例：ABC-1234）："); return
        try:
            n = int(text)
        except ValueError:
            plate_try = text.upper().replace(" ", "")
            v = Vehicle.query.filter_by(user_id=user.id, plate=plate_try).first()
            if v:
                conv.payload = {**conv.payload, "vehicle_id": v.id, "plate": v.plate}
                conv.state = "ask_service"; db.session.commit()
                _reply(event.reply_token, f"已選擇：{v.plate}\n" + services_text()); return
            _reply(event.reply_token, "格式不正確，請輸入清單中的序號（例如：1），或輸入「新增」新增新車輛。"); return

        opts = conv.payload.get("vehicle_options") or []
        chosen = next((o for o in opts if o["i"] == n), None)
        if not chosen:
            _reply(event.reply_token, "序號不在清單中，請重新輸入（例如：1）。"); return
        conv.payload = {**conv.payload, "vehicle_id": chosen["id"], "plate": chosen["plate"]}
        conv.state = "ask_service"; db.session.commit()
        _reply(event.reply_token, f"已選擇：{chosen['plate']}\n" + services_text()); return

    if conv.state == "ask_plate":
        plate = text.upper().replace(" ", "")
        if not PLATE_RE.match(plate):
            _reply(event.reply_token, "車牌格式不太對，請再輸入一次（例：ABC-1234）"); return
        v = Vehicle.query.filter_by(user_id=user.id, plate=plate).first()
        if not v:
            v = Vehicle(user_id=user.id, plate=plate)
            db.session.add(v); db.session.commit()
        conv.payload = {**conv.payload, "vehicle_id": v.id, "plate": v.plate}
        conv.state = "ask_service"; db.session.commit()
        _reply(event.reply_token, "已選擇車輛 ✅\n" + services_text()); return

    if conv.state == "ask_service":
        s = Service.query.filter(Service.name.ilike(f"%{text}%")).first()
        if not s:
            _reply(event.reply_token, "找不到這個服務名稱，請改用清單中的名稱回覆喔～\n" + services_text()); return
        conv.payload = {**conv.payload, "service_id": s.id, "service_name": s.name}
        conv.state = "ask_datetime"; db.session.commit()
        _reply(event.reply_token, "請輸入預約時間（格式：YYYY-MM-DD HH:MM，例如 2025-10-20 14:30）："); return

    if conv.state == "ask_datetime":
        try:
            when = datetime.strptime(text, "%Y-%m-%d %H:%M")
        except ValueError:
            _reply(event.reply_token, "時間格式不正確，請用 YYYY-MM-DD HH:MM（例 2025-10-20 14:30）"); return
        ok, msg = check_capacity(when)
        if not ok:
            _reply(event.reply_token, msg); return
        conv.payload = {**conv.payload, "booked_at": when.strftime("%Y-%m-%d %H:%M")}
        conv.state = "confirm"; db.session.commit()
        p = conv.payload
        confirm_msg = (
            "請確認以下預約資訊（回覆「確認」送出 / 「取消」放棄）：\n"
            f"- 姓名：{p.get('name')}\n"
            f"- 電話：{p.get('phone')}\n"
            f"- 車牌：{p.get('plate')}\n"
            f"- 服務：{p.get('service_name')}\n"
            f"- 時間：{p.get('booked_at')}\n"
        )
        _reply(event.reply_token, confirm_msg); return

    if conv.state == "confirm":
        if text in ["確認", "送出", "ok", "OK"]:
            p = conv.payload
            user.name = p.get("name") or user.name
            user.phone = p.get("phone") or user.phone
            db.session.add(user); db.session.commit()

            booked_at = datetime.strptime(p["booked_at"], "%Y-%m-%d %H:%M")
            order = Order(
                user_id=user.id,
                vehicle_id=p.get("vehicle_id"),
                status="pending",
                booked_at=booked_at,
                note=f"車牌:{p.get('plate')}"
            )
            db.session.add(order); db.session.commit()

            item = OrderItem(order_id=order.id, service_id=p["service_id"], qty=1, unit_price=0, subtotal=0)
            db.session.add(item); db.session.commit()

            reset_conv(conv)
            _reply(event.reply_token, f"✅ 預約成功！\n訂單編號 #{order.id}\n時間：{booked_at:%Y-%m-%d %H:%M}\n若需更改請輸入「我的預約」。")
            return
        _reply(event.reply_token, "若要送出請回覆「確認」，或輸入「取消」離開流程。")
        return

    _reply(
        event.reply_token,
        "嗨～我是機車行助理 🤖\n"
        "輸入「預約」開始預約維修/保養（會先選車）\n"
        "輸入「我的預約」查詢近期預約\n"
        "輸入「取消預約」取消未來行程\n"
        "輸入「調整時間」更改預約時間\n"
        "輸入「我的車輛」查看/新增車輛\n"
        "輸入「設定」更新姓名/手機/車牌\n"
        "輸入「取消」隨時離開流程"
    )

# ---------- Seed ----------
def seed_services():
    if Service.query.count() == 0:
        db.session.add_all([
            Service(name="更換機油", base_price=400, duration_min=20, recommend_days=90),
            Service(name="更換齒輪油", base_price=200, duration_min=15, recommend_days=180),
            Service(name="一般保養檢查", base_price=0, duration_min=30, recommend_days=180),
            Service(name="煞車皮更換", base_price=600, duration_min=40, recommend_days=365),
        ])
        db.session.commit()

def seed_slots():
    if ShopSlot.query.count() == 0:
        # 週一~週六 09:00-18:00，30 分鐘一格，每格容量 2
        for wd in range(0, 6):
            db.session.add(ShopSlot(
                weekday=wd,
                start_time=dtime(9, 0),
                end_time=dtime(18, 0),
                interval_min=30,
                capacity=2
            ))
        db.session.commit()

# ---------- Admin ----------
app.config["BASIC_AUTH_USERNAME"] = os.getenv("ADMIN_USERNAME", "admin")
app.config["BASIC_AUTH_PASSWORD"] = os.getenv("ADMIN_PASSWORD", "changeme")
app.config["BASIC_AUTH_FORCE"] = False
basic_auth = BasicAuth(app)

class SecuredModelView(ModelView):
    def is_accessible(self):
        return True
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
    # 只保護後台，其它像 /callback、/healthz 都放行
    if request.path.startswith("/admin"):
        if not basic_auth.authenticate():
            return basic_auth.challenge()





# ---------- Boot ----------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed_services()
        seed_slots()        # 初次可幫你塞營業時段
        setup_admin(app)    # 啟用 /admin 與 /admin/calendar
    app.run(port=5001)
