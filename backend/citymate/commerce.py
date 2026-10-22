import json
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, update, func
from .models import Order, Voucher, Outbox, Appointment, Slot, public, utcnow
from .service import fail, uid
from .scripts import RESERVE, ORDER_EVENT


class Commerce:
    def emit(self, db, kind, payload):
        db.add(Outbox(id=uid(), kind=kind, payload=json.dumps(payload)))

    def initialize_stock(self, voucher_id):
        key = self.key("stock:" + voucher_id)
        if self.r.exists(key):
            return
        with self.r.lock(self.key("lock:stock:" + voucher_id), timeout=10, blocking_timeout=2):
            if self.r.exists(key):
                return
            with self.db() as db:
                voucher = db.get(Voucher, voucher_id)
                if not voucher:
                    fail(404, "优惠券不存在")
                prior = db.scalar(
                    select(func.count()).select_from(Order).where(Order.voucher_id == voucher_id)
                )
                # Do not silently rebuild an active admission counter from SQL stock.
                # SQL stock excludes unconsumed reservations and cannot prove availability.
                if (
                    prior
                    or self.r.exists(self.key("buyers:" + voucher_id))
                    or self.r.exists(self.key("initialized:" + voucher_id))
                ):
                    fail(503, "库存缓存缺失，需要停止抢购后核对订单与待处理消息")
                self.r.set(key, voucher.stock, nx=True)
                self.r.set(self.key("initialized:" + voucher_id), "1")

    def claim(self, user_id, voucher_id):
        with self.db() as db:
            voucher = db.get(Voucher, voucher_id)
            if not voucher:
                fail(404, "优惠券不存在")
            starts = int(voucher.starts_at.replace(tzinfo=timezone.utc).timestamp())
            ends = int(voucher.ends_at.replace(tzinfo=timezone.utc).timestamp())
        self.initialize_stock(voucher_id)
        order_id = self.identifier()
        result, selected = self.r.eval(
            RESERVE,
            4,
            self.key("stock:" + voucher_id),
            self.key("buyers:" + voucher_id),
            self.key("order:" + order_id),
            self.key("orders"),
            user_id,
            order_id,
            voucher_id,
            starts,
            ends,
        )
        if result not in {"accepted", "existing"}:
            fail(
                409 if result in {"sold_out", "closed"} else 503,
                {"sold_out": "已抢完", "closed": "不在活动时间内", "unavailable": "库存暂不可用"}[
                    result
                ],
            )
        return {
            "order_id": selected,
            "replayed": result == "existing",
            "status": "processing",
            "message": "请求已受理，请查询订单结果；未发生真实支付",
        }

    def process_order(self, payload):
        order_id, user_id, voucher_id = (
            payload["order_id"],
            payload["user_id"],
            payload["voucher_id"],
        )
        with self.db.begin() as db:
            # Lock voucher before the idempotency read to serialize duplicate deliveries.
            voucher = db.scalar(select(Voucher).where(Voucher.id == voucher_id).with_for_update())
            if db.get(Order, order_id):
                return
            if not voucher:
                raise ValueError("Unknown voucher in stream")
            purchase = f"{user_id}:{voucher_id}"
            exists = db.scalar(select(Order).where(Order.purchase_key == purchase))
            success = (
                not exists
                and db.execute(
                    update(Voucher)
                    .where(Voucher.id == voucher_id, Voucher.stock > 0)
                    .values(stock=Voucher.stock - 1)
                ).rowcount
                == 1
            )
            status = "ready" if success else "rejected"
            db.add(
                Order(
                    id=order_id,
                    user_id=user_id,
                    voucher_id=voucher_id,
                    purchase_key=purchase if success else None,
                    status=status,
                    price_cents=voucher.price_cents,
                    note="演示订单，未支付" if success else "库存或重复购买校验失败",
                )
            )
            self.emit(db, "order", {**payload, "status": status})

    def order(self, user_id, order_id):
        with self.db() as db:
            order = db.get(Order, order_id)
            if order and order.user_id == user_id:
                return public(order)
        data = self.r.hgetall(self.key("order:" + order_id))
        if data.get("user_id") != user_id:
            fail(404, "订单不存在")
        return {"id": order_id, **data}

    def orders(self, user_id):
        with self.db() as db:
            return [
                public(o)
                for o in db.scalars(
                    select(Order)
                    .where(Order.user_id == user_id)
                    .order_by(Order.created_at.desc())
                    .limit(100)
                ).all()
            ]

    def cancel_order(self, user_id, order_id):
        with self.db.begin() as db:
            order = db.scalar(
                select(Order)
                .where(Order.id == order_id, Order.user_id == user_id)
                .with_for_update()
            )
            if not order:
                fail(404, "订单尚未生成或不存在，请稍后查询")
            if order.status == "cancelled":
                return public(order)
            if order.status != "ready":
                fail(409, "当前订单不能取消")
            order.status, order.purchase_key = "cancelled", None
            db.execute(
                update(Voucher)
                .where(Voucher.id == order.voucher_id)
                .values(stock=Voucher.stock + 1)
            )
            self.emit(
                db,
                "order",
                {
                    "order_id": order.id,
                    "user_id": user_id,
                    "voucher_id": order.voucher_id,
                    "status": "cancelled",
                },
            )
            result = public(order)
        return result

    def dispatch(self, limit=100):
        sent = 0
        for _ in range(limit):
            with self.db.begin() as db:
                item = db.scalar(
                    select(Outbox)
                    .where(Outbox.done == 0)
                    .order_by(Outbox.id)
                    .with_for_update()
                    .limit(1)
                )
                if not item:
                    break
                p = json.loads(item.payload)
                if item.kind == "order":
                    self.r.eval(
                        ORDER_EVENT,
                        4,
                        self.key("stock:" + p["voucher_id"]),
                        self.key("buyers:" + p["voucher_id"]),
                        self.key("order:" + p["order_id"]),
                        self.key("event:" + item.id),
                        p["user_id"],
                        p["order_id"],
                        p["status"],
                        p["voucher_id"],
                    )
                elif item.kind == "note":
                    self.deliver_note(p["note_id"], db)
                item.done = 1
                sent += 1
        return sent

    def draft_appointment(self, user_id, shop_id, slot, party_size):
        with self.db.begin() as db:
            target = db.get(Slot, (shop_id, slot))
            if not target or target.seats < party_size:
                fail(409, "预约时段不存在或余量不足")
            if datetime.strptime(slot, "%Y-%m-%d %H:%M") <= datetime.now(
                ZoneInfo(self.cfg.timezone)
            ).replace(tzinfo=None):
                fail(409, "预约时段已过期")
            appointment = Appointment(
                id=uid(),
                user_id=user_id,
                shop_id=shop_id,
                slot=slot,
                party_size=party_size,
                status="draft",
            )
            db.add(appointment)
            db.flush()
            return public(appointment)

    def confirm_appointment(self, user_id, draft_id):
        with self.db.begin() as db:
            a = db.scalar(
                select(Appointment)
                .where(Appointment.id == draft_id, Appointment.user_id == user_id)
                .with_for_update()
            )
            if not a:
                fail(404, "预约草稿不存在")
            if a.status == "draft":
                if a.created_at < utcnow() - timedelta(minutes=15):
                    fail(409, "草稿已过期，请重新生成")
                target = db.get(Slot, (a.shop_id, a.slot))
                if not target or target.seats < a.party_size:
                    fail(409, "当前余量不足")
                a.status = "pending_review"
            return public(a)

    def appointments(self, user_id=None):
        with self.db() as db:
            stmt = select(Appointment).order_by(Appointment.created_at.desc()).limit(100)
            if user_id:
                stmt = stmt.where(Appointment.user_id == user_id)
            return [public(a) for a in db.scalars(stmt).all()]

    def review(self, appointment_id, approve, reason):
        with self.db.begin() as db:
            a = db.scalar(
                select(Appointment).where(Appointment.id == appointment_id).with_for_update()
            )
            if not a or a.status != "pending_review":
                fail(409, "申请不存在或已经处理")
            if approve:
                if datetime.strptime(a.slot, "%Y-%m-%d %H:%M") <= datetime.now(
                    ZoneInfo(self.cfg.timezone)
                ).replace(tzinfo=None):
                    fail(409, "预约时段已过期")
                changed = db.execute(
                    update(Slot)
                    .where(
                        Slot.shop_id == a.shop_id, Slot.label == a.slot, Slot.seats >= a.party_size
                    )
                    .values(seats=Slot.seats - a.party_size)
                ).rowcount
                if changed != 1:
                    fail(409, "当前余量不足，无法批准")
            a.status, a.decision = ("approved" if approve else "rejected"), reason
            return public(a)
