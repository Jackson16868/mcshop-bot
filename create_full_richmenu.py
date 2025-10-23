# create_full_richmenu.py
import os, certifi
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from dotenv import load_dotenv
import requests
from PIL import Image, ImageDraw, ImageFont
import json

def generate_image(path="menu.png"):
    if os.path.exists(path):
        print("🖼 已找到 menu.png，跳過產生")
        return path
    W, H = 2500, 1686
    img = Image.new("RGB", (W, H), (245, 246, 248))
    draw = ImageDraw.Draw(img)
    boxes = [(0,0,1250,843),(1250,0,2500,843),(0,843,1250,1686),(1250,843,2500,1686)]
    labels = ["🛠 預約維修","📋 我的預約","🏍 我的車輛","⚙️ 設定資料"]
    try:
        font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 72)
    except:
        font = None
    for (x1,y1,x2,y2), label in zip(boxes, labels):
        draw.rectangle([x1,y1,x2,y2], outline=(200,200,200), width=8)
        draw.text((x1+100, y1+350), label, fill=(50,50,50), font=font)
    img.save(path, "PNG")
    print("✅ 已產生 menu.png")
    return path

def main():
    load_dotenv()
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("❌ .env 缺少 LINE_CHANNEL_ACCESS_TOKEN")

    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    s.verify = certifi.where()

    # Step 1: 建立 rich menu
    body = {
        "size": {"width": 2500, "height": 1686},
        "selected": True,
        "name": "mcshop-main-menu",
        "chatBarText": "開啟選單",
        "areas": [
            {"bounds": {"x":0,"y":0,"width":1250,"height":843}, "action": {"type":"message","label":"預約維修","text":"預約"}},
            {"bounds": {"x":1250,"y":0,"width":1250,"height":843}, "action": {"type":"message","label":"我的預約","text":"我的預約"}},
            {"bounds": {"x":0,"y":843,"width":1250,"height":843}, "action": {"type":"message","label":"我的車輛","text":"我的車輛"}},
            {"bounds": {"x":1250,"y":843,"width":1250,"height":843}, "action": {"type":"message","label":"設定資料","text":"設定"}}
        ]
    }

    print("🧾 建立 Rich Menu...")
    resp = s.post("https://api.line.me/v2/bot/richmenu", data=json.dumps(body))
    if resp.status_code != 200:
        print("❌ 建立失敗:", resp.text)
        return
    rich_id = resp.json()["richMenuId"]
    print(f"✅ Rich Menu 建立成功：{rich_id}")

    # Step 2: 上傳圖片
    img_path = generate_image("menu.png")
    print("📤 上傳圖片...")
    with open(img_path, "rb") as f:
        resp = s.post(f"https://api.line.me/v2/bot/richmenu/{rich_id}/content",
                      data=f,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "image/png"})
    if resp.status_code != 200:
        print("❌ 圖片上傳失敗:", resp.text)
        return
    print("✅ 圖片上傳成功!")

    # Step 3: 設為預設
    print("🔗 綁定預設 Rich Menu...")
    resp = s.post(f"https://api.line.me/v2/bot/user/all/richmenu/{rich_id}", data=b"", headers={"Content-Length":"0"})
    if resp.status_code != 200:
        print("❌ 綁定失敗:", resp.text)
        return
    print("🎉 Done! Rich Menu 已啟用:", rich_id)
    print("👉 封鎖→解除封鎖 BOT，選單就會顯示")

if __name__ == "__main__":
    main()
