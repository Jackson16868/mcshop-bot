from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    line_user_id = db.Column(db.String(64), unique=True, index=True, nullable=False)
    name = db.Column(db.String(64))
    phone = db.Column(db.String(32))
    note = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # relationships
    vehicles = db.relationship("Vehicle", back_populates="user", cascade="all, delete-orphan")
    orders = db.relationship("Order", backref="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User id={self.id} line_user_id={self.line_user_id!r}>"

class Service(db.Model):
    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False, unique=True)
    base_price = db.Column(db.Integer, default=0)         # 單位：元
    duration_min = db.Column(db.Integer, default=30)      # 施工時間（分鐘）
    recommend_days = db.Column(db.Integer, default=180)   # 建議保養間隔（天）

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Service id={self.id} name={self.name!r}>"

class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    # ✅ 加上這行：綁定使用者的車輛
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=True, index=True)

    status = db.Column(db.String(32), default="pending")
    booked_at = db.Column(db.DateTime)
    note = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    # ✅ 可選：加反向查詢
    vehicle = db.relationship("Vehicle")


class OrderItem(db.Model):
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False, index=True)

    qty = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Integer, default=0)
    subtotal = db.Column(db.Integer, default=0)

    order = db.relationship("Order", back_populates="items")
    service = db.relationship("Service")

    def __repr__(self) -> str:
        return f"<OrderItem id={self.id} order_id={self.order_id} service_id={self.service_id}>"

class Conversation(db.Model):
    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True)
    line_user_id = db.Column(db.String(64), index=True, unique=True, nullable=False)
    state = db.Column(db.String(32), default="idle")
    payload = db.Column(db.JSON, default=dict)  # 使用 callable，避免所有 row 共享同一個物件

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Conversation id={self.id} line_user_id={self.line_user_id!r} state={self.state!r}>"

class Vehicle(db.Model):
    __tablename__ = "vehicles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    plate = db.Column(db.String(16), nullable=False)  # 例：ABC-1234
    brand = db.Column(db.String(32))                  # 例：Yamaha / Kymco / SYM
    model = db.Column(db.String(64))                  # 例：Many 110 / JET SL / BWS
    year = db.Column(db.Integer)                      # 可選：年份
    note = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", back_populates="vehicles")

    __table_args__ = (
        UniqueConstraint("user_id", "plate", name="uq_vehicle_user_plate"),
    )

    def __repr__(self) -> str:
        return f"<Vehicle id={self.id} user_id={self.user_id} plate={self.plate!r}>"

class ShopSlot(db.Model):
    __tablename__ = "shop_slots"
    id = db.Column(db.Integer, primary_key=True)
    # 0=Monday ~ 6=Sunday
    weekday = db.Column(db.Integer, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)   # 例：09:00
    end_time   = db.Column(db.Time, nullable=False)   # 例：18:00
    interval_min = db.Column(db.Integer, default=30)  # 每格間距（分鐘）
    capacity = db.Column(db.Integer, default=2)       # 同時可服務筆數

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("weekday", "start_time", "end_time", name="uq_shopslot_window"),
    )

    def __repr__(self):
        return f"<ShopSlot weekday={self.weekday} {self.start_time}-{self.end_time} cap={self.capacity}>"