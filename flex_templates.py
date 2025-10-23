# flex_templates.py
from datetime import datetime

def bubble_vehicle_picker(options):
    # options: [{"i":1,"label":"AAA-1234 | YAMAHA Many"}]
    btns = []
    for opt in options[:12]:
        btns.append({
            "type": "button",
            "style": "primary",
            "margin": "sm",
            "action": {
                "type": "postback",
                "label": opt["label"][:20],
                "data": f"VEHICLE_PICK:{opt['i']}"
            }
        })
    btns.append({
        "type": "button",
        "style": "secondary",
        "margin": "md",
        "action": {"type": "postback", "label": "新增車輛", "data": "VEHICLE_ADD"}
    })
    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "請選擇車輛", "weight": "bold", "size": "lg"},
                {"type": "separator", "margin": "md"},
            ] + (btns or [{"type": "text", "text": "尚無車輛", "color": "#888888"}])
        }
    }


def bubble_services_page(services, page: int, per_page: int = 6):
    total = len(services)
    start = (page - 1) * per_page
    page_items = services[start:start + per_page]

    contents = []
    if not page_items:
        contents = [{"type": "text", "text": "暫無服務項目", "color": "#888888"}]
    else:
        for s in page_items:
            contents += [
                {
                    "type": "box",
                    "layout": "baseline",
                    "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": s["name"], "wrap": True, "weight": "bold", "flex": 5},
                        {"type": "text", "text": f"約{s['mins']}分", "size": "sm", "color": "#888888", "flex": 2}
                    ]
                },
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": f"選擇「{s['name']}」",
                        "data": f"SVC_PICK:{s['name']}"
                    }
                },
                {"type": "separator", "margin": "sm"},
            ]

    footer_btns = []
    if page > 1:
        footer_btns.append({
            "type": "button",
            "style": "secondary",
            "action": {"type": "postback", "label": "上一頁", "data": "SVC_PREV"}
        })
    if page * per_page < total:
        footer_btns.append({
            "type": "button",
            "style": "secondary",
            "action": {"type": "postback", "label": "下一頁", "data": "SVC_NEXT"}
        })
    if not footer_btns:
        # 單頁情況給個無害 postback（後端可忽略）
        footer_btns = [{
            "type": "button",
            "style": "secondary",
            "action": {"type": "postback", "label": "—", "data": "SVC_NOP"}
        }]

    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "請選擇服務", "weight": "bold", "size": "lg"},
                {"type": "separator", "margin": "md"},
                {"type": "box", "layout": "vertical", "spacing": "md", "margin": "md", "contents": contents}
            ]
        },
        "footer": {"type": "box", "layout": "horizontal", "spacing": "sm", "contents": footer_btns}
    }

def bubble_timeslots(slots: list[datetime], page: int, per_page: int = 6):
    total = len(slots)
    start = (page - 1) * per_page
    page_items = slots[start:start + per_page]
    btns = []
    for dt in page_items:
        btns.append({
            "type": "button",
            "style": "primary",
            "height": "sm",
            "action": {
                "type": "postback",
                "label": dt.strftime("%m/%d %H:%M"),
                "data": f"SLOT_PICK:{dt:%Y-%m-%d %H:%M}"
            }
        })
    if not btns:
        btns = [{"type": "text", "text": "近期沒有可預約時段", "color": "#888888"}]

    footer = []
    if page > 1:
        footer.append({
            "type": "button",
            "style": "secondary",
            "action": {"type": "postback", "label": "上一頁", "data": "SLOT_PREV"}
        })
    if page * per_page < total:
        footer.append({
            "type": "button",
            "style": "secondary",
            "action": {"type": "postback", "label": "下一頁", "data": "SLOT_NEXT"}
        })
    if not footer:
        # 沒有分頁就提供「取消流程」
        footer = [{
            "type": "button",
            "style": "secondary",
            "action": {"type": "postback", "label": "取消流程", "data": "FLOW_CANCEL"}
        }]

    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "請選擇時段", "weight": "bold", "size": "lg"},
                {"type": "separator", "margin": "md"},
            ] + btns
        },
        "footer": {"type": "box", "layout": "horizontal", "spacing": "sm", "contents": footer}
    }

def bubble_confirm(payload: dict):
    rows = [
        ("姓名", payload.get("name") or "-"),
        ("電話", payload.get("phone") or "-"),
        ("車牌", payload.get("plate") or "-"),
        ("服務", payload.get("service_name") or "-"),
        ("時間", payload.get("booked_at") or "-"),
    ]
    lines = []
    for k, v in rows:
        lines.append({
            "type": "box",
            "layout": "baseline",
            "spacing": "sm",
            "contents": [
                {"type": "text", "text": str(k), "color": "#888888", "size": "sm", "flex": 2},
                {"type": "text", "text": str(v) if str(v).strip() else "-", "wrap": True, "size": "sm", "flex": 5}
            ]
        })
    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "請確認預約資訊", "weight": "bold", "size": "lg"},
                {"type": "separator", "margin": "md"},
                {"type": "box", "layout": "vertical", "spacing": "md", "margin": "md", "contents": lines}
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary",
                 "action": {"type": "postback", "label": "確認送出", "data": "CONFIRM_SUBMIT"}},
                {"type": "button", "style": "secondary",
                 "action": {"type": "postback", "label": "取消流程", "data": "FLOW_CANCEL"}}
            ]
        }
    }


def bubble_orders(rows, mode_label=None):
    """
    用於舊式清單（非 carousel）。依 mode_label 決定按鈕行為：
      - 包含「取消」→ CANCEL#<id>
      - 包含「更改時間」→ RESCHEDULE#<id>
      - 其他 → ORD_DETAIL#<id>（後端可忽略或擴充）
    """
    contents = []
    for idx, o in enumerate(rows[:10], start=1):
        t = o["time"]
        # 決定行為
        if mode_label and "取消" in mode_label:
            label = "取消這筆"
            data  = f"CANCEL#{o['id']}"
        elif mode_label and ("更改時間" in mode_label or "調整時間" in mode_label):
            label = "更改時間"
            data  = f"RESCHEDULE#{o['id']}"
        else:
            label = "查看"
            data  = f"ORD_DETAIL#{o['id']}"
        contents.append({
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "margin": "md",
            "contents": [
                {"type": "text", "text": f"{idx}. #{o['id']}｜{o.get('plate','')}".strip(), "weight": "bold"},
                {"type": "text", "text": f"{t}｜{o['status']}", "size": "sm", "color": "#666666"},
                {"type": "button", "style": "primary", "height": "sm",
                 "action": {"type": "postback", "label": label, "data": data}}
            ]
        })
    if not contents:
        contents = [{"type": "text", "text": "目前沒有預約", "color": "#888888"}]
    title = "最近預約" if not mode_label else f"選擇要{mode_label}的預約"
    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": title, "weight": "bold", "size": "lg"},
                {"type": "separator", "margin": "md"},
                {"type": "box", "layout": "vertical", "contents": contents}
            ]
        }
    }

# === 單筆訂單詳情 bubble（含取消/調整時間的 Postback）===
def bubble_order_detail(order_row: dict):
    """
    order_row: {
      "id": int,
      "plate": str,
      "status": str,
      "services": str,
      "time": str
    }
    """
    lines = [
        {"type":"box","layout":"baseline","spacing":"sm","contents":[
            {"type":"text","text":"編號","size":"sm","color":"#888888","flex":2},
            {"type":"text","text":f"#{order_row['id']}", "size":"sm","wrap":True,"flex":5}
        ]},
        {"type":"box","layout":"baseline","spacing":"sm","contents":[
            {"type":"text","text":"狀態","size":"sm","color":"#888888","flex":2},
            {"type":"text","text":order_row.get("status","-"), "size":"sm","wrap":True,"flex":5}
        ]},
        {"type":"box","layout":"baseline","spacing":"sm","contents":[
            {"type":"text","text":"時間","size":"sm","color":"#888888","flex":2},
            {"type":"text","text":order_row.get("time","未排定"), "size":"sm","wrap":True,"flex":5}
        ]},
        {"type":"box","layout":"baseline","spacing":"sm","contents":[
            {"type":"text","text":"車牌","size":"sm","color":"#888888","flex":2},
            {"type":"text","text":(order_row.get("plate") or "-"), "size":"sm","wrap":True,"flex":5}
        ]},
        {"type":"box","layout":"baseline","spacing":"sm","contents":[
            {"type":"text","text":"服務","size":"sm","color":"#888888","flex":2},
            {"type":"text","text":(order_row.get("services") or "-"), "size":"sm","wrap":True,"flex":5}
        ]},
    ]
    return {
      "type":"bubble",
      "body":{"type":"box","layout":"vertical","contents":[
        {"type":"text","text":"預約詳情","weight":"bold","size":"lg"},
        {"type":"separator","margin":"md"},
        {"type":"box","layout":"vertical","spacing":"md","margin":"md","contents":lines}
      ]},
      "footer":{"type":"box","layout":"vertical","spacing":"sm","contents":[
        {"type":"button","style":"primary",
         "action":{"type":"postback","label":"取消預約","data":f"CANCEL#{order_row['id']}"}},
        {"type":"button","style":"secondary",
         "action":{"type":"postback","label":"調整時間","data":f"RESCHEDULE#{order_row['id']}"}}
      ]}
    }

# === 多筆 orders 組成 carousel（最多 10 張）===
def carousel_orders_full(rows: list[dict]):
    bubbles = [bubble_order_detail(r) for r in rows[:10]]  # LINE 限制最多 10 張
    if not bubbles:
        bubbles = [{
          "type":"bubble",
          "body":{"type":"box","layout":"vertical","contents":[
            {"type":"text","text":"目前沒有預約","weight":"bold","size":"lg"},
            {"type":"separator","margin":"md"},
            {"type":"text","text":"輸入「預約」開始建立新預約","size":"sm","color":"#888888","margin":"md"}
          ]}
        }]
    return {"type":"carousel","contents":bubbles}

# === 取消預約確認 bubble（兩個按鈕：確認、返回） ===
def bubble_cancel_confirm(order_row: dict):
    """
    order_row: { id, plate, status, services, time }
    """
    lines = [
        {"type":"box","layout":"baseline","spacing":"sm","contents":[
            {"type":"text","text":"編號","size":"sm","color":"#888888","flex":2},
            {"type":"text","text":f"#{order_row['id']}", "size":"sm","wrap":True,"flex":5}
        ]},
        {"type":"box","layout":"baseline","spacing":"sm","contents":[
            {"type":"text","text":"時間","size":"sm","color":"#888888","flex":2},
            {"type":"text","text":order_row.get("time","未排定"), "size":"sm","wrap":True,"flex":5}
        ]},
        {"type":"box","layout":"baseline","spacing":"sm","contents":[
            {"type":"text","text":"車牌","size":"sm","color":"#888888","flex":2},
            {"type":"text","text":(order_row.get("plate") or "-"), "size":"sm","wrap":True,"flex":5}
        ]},
        {"type":"box","layout":"baseline","spacing":"sm","contents":[
            {"type":"text","text":"服務","size":"sm","color":"#888888","flex":2},
            {"type":"text","text":(order_row.get("services") or "-"), "size":"sm","wrap":True,"flex":5}
        ]},
    ]
    return {
        "type":"bubble",
        "body":{"type":"box","layout":"vertical","contents":[
            {"type":"text","text":"確認取消這筆預約？","weight":"bold","size":"lg"},
            {"type":"separator","margin":"md"},
            {"type":"box","layout":"vertical","spacing":"md","margin":"md","contents":lines}
        ]},
        "footer":{"type":"box","layout":"vertical","spacing":"sm","contents":[
            {"type":"button","style":"primary",
             "action":{"type":"postback","label":"確認取消", "data":f"CANCEL_CONFIRM#{order_row['id']}"}},
            {"type":"button","style":"secondary",
             "action":{"type":"postback","label":"返回", "data":"BACK_MY_ORDERS"}}
        ]}
    }

def bubble_new_booking_picker(payload: dict, initial_iso: str, min_iso: str, max_iso: str):
    """
    顯示要預約的新時間的 datetimepicker（尚未有訂單）
    payload 用於顯示：name/phone/plate/service_name
    """
    lines = []
    for k, v in [
        ("姓名", payload.get("name") or "-"),
        ("電話", payload.get("phone") or "-"),
        ("車牌", payload.get("plate") or "-"),
        ("服務", payload.get("service_name") or "-"),
    ]:
        lines.append({
            "type":"box","layout":"baseline","spacing":"sm","contents":[
                {"type":"text","text":k,"size":"sm","color":"#888888","flex":2},
                {"type":"text","text":(str(v).strip() or "-"),"size":"sm","wrap":True,"flex":5}
            ]
        })

    return {
        "type":"bubble",
        "body":{"type":"box","layout":"vertical","contents":[
            {"type":"text","text":"選擇預約日期時間","weight":"bold","size":"lg"},
            {"type":"separator","margin":"md"},
            {"type":"box","layout":"vertical","spacing":"md","margin":"md","contents":lines}
        ]},
        "footer":{"type":"box","layout":"vertical","spacing":"sm","contents":[
            {
                "type":"button","style":"primary",
                "action":{
                    "type":"datetimepicker",
                    "label":"選日期時間",
                    "data":"NEWBOOK",
                    "mode":"datetime",
                    "initial": initial_iso,
                    "min": min_iso,
                    "max": max_iso
                }
            },
            {"type":"button","style":"secondary",
             "action":{"type":"postback","label":"取消流程","data":"FLOW_CANCEL"}}
        ]}
    }




# === 改期：用 LINE Datetime Picker 的 bubble ===
def bubble_reschedule_picker(order_row: dict, initial_iso: str, min_iso: str, max_iso: str):
    """
    order_row: { id, plate, status, services, time }
    initial_iso/min_iso/max_iso: 'YYYY-MM-DDTHH:MM' (LINE datetimepicker 格式)
    """
    lines = [
        {"type":"box","layout":"baseline","spacing":"sm","contents":[
            {"type":"text","text":"編號","size":"sm","color":"#888888","flex":2},
            {"type":"text","text":f"#{order_row['id']}", "size":"sm","wrap":True,"flex":5}
        ]},
        {"type":"box","layout":"baseline","spacing":"sm","contents":[
            {"type":"text","text":"目前時間","size":"sm","color":"#888888","flex":2},
            {"type":"text","text":order_row.get("time","未排定"), "size":"sm","wrap":True,"flex":5}
        ]},
        {"type":"box","layout":"baseline","spacing":"sm","contents":[
            {"type":"text","text":"車牌","size":"sm","color":"#888888","flex":2},
            {"type":"text","text":(order_row.get("plate") or "-"), "size":"sm","wrap":True,"flex":5}
        ]},
        {"type":"box","layout":"baseline","spacing":"sm","contents":[
            {"type":"text","text":"服務","size":"sm","color":"#888888","flex":2},
            {"type":"text","text":(order_row.get("services") or "-"), "size":"sm","wrap":True,"flex":5}
        ]},
    ]
    return {
        "type":"bubble",
        "body":{"type":"box","layout":"vertical","contents":[
            {"type":"text","text":"選擇新的日期時間","weight":"bold","size":"lg"},
            {"type":"separator","margin":"md"},
            {"type":"box","layout":"vertical","spacing":"md","margin":"md","contents":lines}
        ]},
        "footer":{"type":"box","layout":"vertical","spacing":"sm","contents":[
            {
                "type":"button","style":"primary",
                "action":{
                    "type":"datetimepicker",
                    "label":"選日期時間",
                    "data": f"RESCHEDULE#{order_row['id']}",
                    "mode":"datetime",
                    "initial": initial_iso,   # e.g. "2025-10-20T14:30"
                    "min": min_iso,           # e.g. "2025-10-01T09:00"
                    "max": max_iso            # e.g. "2025-12-31T18:00"
                }
            },
            {"type":"button","style":"secondary",
             "action":{"type":"postback","label":"返回", "data":"BACK_MY_ORDERS"}}
        ]}
    }


def bubble_vehicle_card(vrow):
    # vrow: {"id":int, "plate":str, "brand":str|None, "model":str|None}
    subtitle = " ".join([x for x in [vrow.get("brand"), vrow.get("model")] if x]) or "-"
    return {
        "type":"bubble",
        "body":{
            "type":"box","layout":"vertical","spacing":"sm","contents":[
                {"type":"text","text":vrow.get("plate","-"),"weight":"bold","size":"lg"},
                {"type":"text","text":subtitle,"size":"sm","color":"#666666"}
            ]
        },
        "footer":{
            "type":"box","layout":"vertical","spacing":"sm","contents":[
                {"type":"button","style":"primary",
                 "action":{"type":"postback","label":"用這台預約","data":f"VEHICLE_USE:{vrow['id']}"}}
            ]
        }
    }

def carousel_my_vehicles(vrows):
    # vrows: list of dict (最多 10 張)
    bubbles = [bubble_vehicle_card(v) for v in vrows[:10]]
    # 追加一張「新增車輛」卡
    bubbles.append({
        "type":"bubble",
        "body":{"type":"box","layout":"vertical","spacing":"sm","contents":[
            {"type":"text","text":"新增車輛","weight":"bold","size":"lg"},
            {"type":"text","text":"綁定你的新車牌","size":"sm","color":"#666666"}
        ]},
        "footer":{"type":"box","layout":"vertical","spacing":"sm","contents":[
            {"type":"button","style":"secondary",
             "action":{"type":"postback","label":"新增車輛","data":"VEHICLE_ADD"}}
        ]}
    })
    return {"type":"carousel","contents":bubbles}

def bubble_settings(user):
    name  = user.name or "-"
    phone = user.phone or "-"
    lines = [
        {"type":"box","layout":"baseline","spacing":"sm","contents":[
            {"type":"text","text":"姓名","size":"sm","color":"#888888","flex":2},
            {"type":"text","text":name,"size":"sm","flex":5,"wrap":True}
        ]},
        {"type":"box","layout":"baseline","spacing":"sm","contents":[
            {"type":"text","text":"電話","size":"sm","color":"#888888","flex":2},
            {"type":"text","text":phone,"size":"sm","flex":5,"wrap":True}
        ]},
    ]
    return {
        "type":"bubble",
        "body":{"type":"box","layout":"vertical","contents":[
            {"type":"text","text":"設定","weight":"bold","size":"lg"},
            {"type":"separator","margin":"md"},
            {"type":"box","layout":"vertical","spacing":"md","margin":"md","contents":lines}
        ]},
        "footer":{"type":"box","layout":"vertical","spacing":"sm","contents":[
            {"type":"button","style":"primary",
             "action":{"type":"postback","label":"修改姓名","data":"SETTINGS_EDIT_NAME"}},
            {"type":"button","style":"primary",
             "action":{"type":"postback","label":"修改電話","data":"SETTINGS_EDIT_PHONE"}},
            {"type":"button","style":"secondary",
             "action":{"type":"postback","label":"我的車輛","data":"MY_VEHICLES"}}
        ]}
    }

def bubble_booking_success(order_id, payload):
    """
    成功預約通知 Flex
    """
    return {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": "https://cdn-icons-png.flaticon.com/512/845/845646.png",
            "size": "full",
            "aspectRatio": "1.91:1",
            "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "✅ 預約成功！", "weight": "bold", "size": "xl", "color": "#00AA00"},
                {"type": "separator", "margin": "md"},
                {"type": "box", "layout": "vertical", "margin": "md", "contents": [
                    {"type": "text", "text": f"訂單編號：#{order_id}", "size": "md"},
                    {"type": "text", "text": f"車牌：{payload.get('plate','-')}", "size": "md"},
                    {"type": "text", "text": f"服務項目：{payload.get('service','-')}", "size": "md"},
                    {"type": "text", "text": f"預約時間：{payload.get('booked_at','-')}", "size": "md"},
                ]}
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "action": {"type": "postback", "label": "查看我的預約", "data": "BACK_MY_ORDERS"},
                    "style": "primary", "color": "#2E86C1"
                }
            ]
        }
    }
