# mcshop-bot

機車行 LINE Bot：預約/改期/取消、車輛管理、營業日曆（Flask + SQLAlchemy + LINE Messaging API + Flask-Admin）

## 功能
- 預約維修/保養（支援選車、選服務、輸入時段）
- 調整時間、取消預約
- 車輛建立 / 查詢
- 營業時段設定（ShopSlot），自動檢查容量
- 後台管理（/admin）：Users / Vehicles / Services / Orders / ShopSlots / Calendar

---

## 環境需求
- Python 3.11 或 3.12（避免 3.14 造成 pydantic v1 相容性警告）
- Postgres 14+（或你可改為 sqlite 測試）
- ngrok（或類似工具）用來提供外網 Webhook

---

## 安裝與啟動

```bash
# 1) 取得程式碼
git clone git@github.com:Jackson16868/mcshop-bot.git
cd mcshop-bot

# 2) 建立虛擬環境 & 安裝套件
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3) 設定環境變數
cp .env.example .env
# 編輯 .env，填入 DATABASE_URL、LINE_CHANNEL_SECRET、LINE_CHANNEL_ACCESS_TOKEN 等

# 4) 本機啟動
export $(grep -v '^#' .env | xargs)
python app.py
# 服務會在 http://127.0.0.1:5001

---

## 💡 開發流程（協作建議）

### 1️⃣ 取得專案
```bash
git clone git@github.com:Jackson16868/mcshop-bot.git
cd mcshop-bot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 編輯 .env 後執行
python app.py

git pull origin main

git checkout -b feature/add-appointment
# 或
git checkout -b jackson-fix-richmenu

git add .
git commit -m "feat: 新增預約功能"
git push origin feature/add-appointment

git pull origin main
git merge main

