import hashlib
import json
import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from redis.exceptions import LockError
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from .models import User, Shop, Voucher, Slot, public, utcnow
from .scripts import VERIFY_CODE


def fail(status, message):
    raise HTTPException(status, message)


def uid():
    return uuid.uuid4().hex


class Core:
    def __init__(self, settings, sessions, redis):
        self.cfg, self.db, self.r = settings, sessions, redis
        self.cache_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cache")

    def key(self, suffix):
        return self.cfg.prefix + suffix

    def close(self):
        self.cache_pool.shutdown(wait=True)

    def identifier(self):
        now = int(time.time())
        key = self.key("id:" + datetime.now(timezone.utc).strftime("%Y%m%d"))
        seq = self.r.incr(key)
        if seq == 1:
            self.r.expire(key, 172800)
        if seq >= 2**32:
            fail(503, "编号生成繁忙")
        return str(((now - 1640995200) << 32) | seq)

    def code(self, phone):
        if not self.cfg.demo:
            fail(503, "短信服务尚未配置；本地演示可启用 CITYMATE_DEMO")
        if not self.r.set(self.key("code-rate:" + phone), "1", nx=True, ex=60):
            fail(429, "请等待 60 秒再获取验证码")
        code = f"{secrets.randbelow(1000000):06d}"
        session_id = secrets.token_urlsafe(32)
        key = self.session_key(session_id)
        with self.r.pipeline() as pipe:
            pipe.hset(key, mapping={"phone": phone, "code": code})
            pipe.expire(key, 300)
            pipe.execute()
        return session_id, {"demo": True, "demo_code": code, "message": "演示验证码，未发送短信"}

    def session_key(self, session_id):
        return self.key("http-session:" + hashlib.sha256(session_id.encode()).hexdigest())

    def login(self, phone, code, session_id):
        if not session_id:
            fail(401, "请先获取验证码")
        key = self.session_key(session_id)
        ok = self.r.eval(VERIFY_CODE, 1, key, phone, code)
        if not ok:
            fail(401, "验证码错误、已使用、已过期或尝试过多")
        try:
            with self.db.begin() as db:
                user = db.scalar(select(User).where(User.phone == phone))
                if user is None:
                    user = User(id=uid(), phone=phone, nickname="城市旅人" + phone[-4:])
                    db.add(user)
                    db.flush()
                user_id = user.id
        except IntegrityError:
            with self.db() as db:
                user_id = db.scalar(select(User.id).where(User.phone == phone))
        user = self.user(user_id, private=True)
        # Rotate the anonymous session ID after login to prevent session fixation.
        new_id = secrets.token_urlsafe(32)
        with self.r.pipeline() as pipe:
            pipe.hset(self.session_key(new_id), "user", json.dumps(user))
            pipe.expire(self.session_key(new_id), self.cfg.session_ttl)
            pipe.delete(key)
            pipe.execute()
        return new_id, {"user": user}

    def authenticate(self, session_id):
        if not session_id:
            fail(401, "请先登录或重新登录")
        key = self.session_key(session_id)
        saved = self.r.hget(key, "user")
        if not saved:
            fail(401, "请先登录或重新登录")
        self.r.expire(key, self.cfg.session_ttl)
        # Reload server-side roles so a role change takes effect immediately.
        return self.user(json.loads(saved)["id"], private=True)

    def logout(self, session_id):
        if session_id:
            self.r.delete(self.session_key(session_id))

    def user(self, user_id, private=False):
        with self.db() as db:
            user = db.get(User, user_id)
            if not user:
                fail(404, "用户不存在")
            data = public(user)
        if not private:
            data.pop("phone")
            data.pop("role")
        return data

    def update_profile(self, user_id, values):
        with self.db.begin() as db:
            user = db.get(User, user_id)
            user.nickname, user.bio = values["nickname"], values["bio"]
        return self.user(user_id, private=True)

    def shops(
        self, category="", query="", budget=None, longitude=None, latitude=None, radius=10, page=1
    ):
        distances = None
        if longitude is not None and latitude is not None:
            nearby = self.r.geosearch(
                self.key("geo"),
                longitude=longitude,
                latitude=latitude,
                radius=radius,
                unit="km",
                sort="ASC",
                count=200,
                withdist=True,
            )
            distances = {item[0]: float(item[1]) for item in nearby}
        with self.db() as db:
            stmt = select(Shop)
            if category:
                stmt = stmt.where(Shop.category == category)
            if query:
                stmt = stmt.where(
                    Shop.name.contains(query, autoescape=True)
                    | Shop.description.contains(query, autoescape=True)
                )
            if budget is not None:
                stmt = stmt.where(Shop.price_cents <= budget)
            if distances is not None:
                stmt = stmt.where(Shop.id.in_(distances))
            if distances is None:
                rows = db.scalars(stmt.order_by(Shop.id).offset((page - 1) * 20).limit(20)).all()
            else:
                rows = db.scalars(stmt).all()
                rows = sorted(rows, key=lambda s: distances[s.id])[(page - 1) * 20 : page * 20]
            return [
                {**public(s), "distance_km": distances[s.id] if distances is not None else None}
                for s in rows
            ]

    def _load_shop(self, shop_id):
        with self.db() as db:
            shop = db.get(Shop, shop_id)
            return public(shop) if shop else None

    def _rebuild_shop(self, shop_id):
        lock = self.r.lock(self.key("lock:shop:" + shop_id), timeout=15, blocking_timeout=2)
        if not lock.acquire():
            return None
        try:
            current = self.r.get(self.key("shop:" + shop_id))
            if current:
                cached = json.loads(current)
                if cached["until"] > time.time():
                    return cached["data"]
            value = self._load_shop(shop_id)
            self.r.set(
                self.key("shop:" + shop_id),
                json.dumps({"data": value, "until": time.time() + (300 if value else 30)}),
                ex=3600 if value else 30,
            )
            return value
        finally:
            try:
                lock.release()
            except LockError:
                pass

    def shop(self, shop_id, viewer=None):
        raw = self.r.get(self.key("shop:" + shop_id))
        cached = json.loads(raw) if raw else None
        if cached and cached["until"] > time.time():
            result = cached["data"]
        elif cached and self.cfg.cache_mode == "logical":
            result = cached["data"]
            # NX limits queued rebuilds as well as actual rebuild concurrency.
            marker = self.key("refresh:" + shop_id)
            if self.r.set(marker, "1", nx=True, ex=20):
                self.cache_pool.submit(self._rebuild_shop, shop_id)
        else:
            result = self._rebuild_shop(shop_id)
            if result is None:
                raw = self.r.get(self.key("shop:" + shop_id))
                if raw is None:
                    fail(503, "商户资料正在更新，请稍后重试")
                result = json.loads(raw)["data"]
        if result is None:
            fail(404, "商户不存在")
        if viewer:
            day = datetime.now(ZoneInfo(self.cfg.timezone)).strftime("%Y%m%d")
            key = self.key(f"uv:{shop_id}:{day}")
            # No raw phone numbers are placed in analytics structures.
            self.r.pfadd(key, hashlib.sha256(viewer.encode()).hexdigest())
            self.r.expire(key, 86400 * 35)
        return result

    def edit_shop(self, shop_id, values):
        with self.r.lock(self.key("lock:shop:" + shop_id), timeout=15, blocking_timeout=3):
            with self.db.begin() as db:
                shop = db.get(Shop, shop_id)
                if not shop:
                    fail(404, "商户不存在")
                for name, value in values.items():
                    setattr(shop, name, value)
            self.r.delete(self.key("shop:" + shop_id))
            self.r.geoadd(self.key("geo"), [values["longitude"], values["latitude"], shop_id])
        return self.shop(shop_id)

    def create_shop(self, values):
        shop_id = self.identifier()
        with self.db.begin() as db:
            db.add(Shop(id=shop_id, **values))
        self.r.geoadd(self.key("geo"), [values["longitude"], values["latitude"], shop_id])
        return self.shop(shop_id)

    def create_voucher(self, values):
        starts, ends = values["starts_at"], values["ends_at"]
        if starts.tzinfo is None or ends.tzinfo is None:
            fail(400, "活动时间必须包含时区")
        starts, ends = starts.astimezone(timezone.utc).replace(tzinfo=None), ends.astimezone(
            timezone.utc
        ).replace(tzinfo=None)
        if ends <= starts or ends <= utcnow():
            fail(400, "结束时间必须晚于开始时间和当前时间")
        self.shop(values["shop_id"])
        voucher_id = self.identifier()
        with self.db.begin() as db:
            voucher = Voucher(id=voucher_id, **{**values, "starts_at": starts, "ends_at": ends})
            db.add(voucher)
            db.flush()
            result = public(voucher)
        self.initialize_stock(voucher_id)
        return result

    def vouchers(self, shop_id=None):
        with self.db() as db:
            stmt = select(Voucher).order_by(Voucher.id)
            if shop_id:
                stmt = stmt.where(Voucher.shop_id == shop_id)
            return [public(v) for v in db.scalars(stmt).all()]

    def slots(self, shop_id):
        with self.db() as db:
            return [
                public(s) for s in db.scalars(select(Slot).where(Slot.shop_id == shop_id)).all()
            ]

    def seed(self):
        """Explicit demo-only setup; never overwrite stock or live user data."""
        if not self.cfg.demo:
            raise RuntimeError("Demo seed requires CITYMATE_DEMO=true")
        shops = [
            (
                "s1",
                "梧桐小馆",
                "美食",
                "适合朋友聚餐的江南菜，提供双人套餐。",
                "上海市徐汇区衡山路 88 号（演示）",
                121.446,
                31.207,
                9800,
                "11:00–22:00",
            ),
            (
                "s2",
                "光影放映室",
                "娱乐",
                "小型电影放映空间，适合周末休闲。",
                "上海市徐汇区复兴中路 120 号（演示）",
                121.455,
                31.216,
                6800,
                "10:00–23:00",
            ),
            (
                "s3",
                "青岚攀岩",
                "运动",
                "室内攀岩体验，包含基础指导，需提前预约。",
                "上海市静安区愚园路 66 号（演示）",
                121.441,
                31.224,
                12800,
                "09:00–21:00",
            ),
            (
                "s4",
                "慢岛咖啡",
                "咖啡",
                "有窗边座位的安静咖啡店，适合阅读。",
                "上海市徐汇区武康路 38 号（演示）",
                121.435,
                31.210,
                4500,
                "08:00–20:00",
            ),
        ]
        with self.db.begin() as db:
            for user_id, phone, name, role in [
                ("demo-admin", "13900000000", "城市管理员", "admin"),
                ("demo-author", "13900000001", "周末观察员", "user"),
            ]:
                if not db.get(User, user_id) and not db.scalar(
                    select(User).where(User.phone == phone)
                ):
                    db.add(User(id=user_id, phone=phone, nickname=name, role=role))
            db.flush()
            for s in shops:
                if not db.get(Shop, s[0]):
                    db.add(
                        Shop(
                            **dict(
                                zip(
                                    [
                                        "id",
                                        "name",
                                        "category",
                                        "description",
                                        "address",
                                        "longitude",
                                        "latitude",
                                        "price_cents",
                                        "hours",
                                    ],
                                    s,
                                )
                            )
                        )
                    )
            db.flush()
            for i, s in enumerate(shops, 1):
                voucher_id = "v" + str(i)
                if not db.get(Voucher, voucher_id):
                    db.add(
                        Voucher(
                            id=voucher_id,
                            shop_id=s[0],
                            title=s[1] + "限量体验券",
                            rules="演示优惠券，有效期内使用；每人限领一张。预约须经商户确认；不包含真实支付。",
                            price_cents=s[7] // 2,
                            stock=10,
                            starts_at=utcnow() - timedelta(days=1),
                            ends_at=utcnow() + timedelta(days=30),
                        )
                    )
                for d in range(1, 8):
                    label = (
                        datetime.now(ZoneInfo(self.cfg.timezone)).date() + timedelta(days=d)
                    ).isoformat() + " 18:00"
                    if not db.get(Slot, (s[0], label)):
                        db.add(Slot(shop_id=s[0], label=label, seats=12))
        for s in shops:
            self.r.geoadd(self.key("geo"), [s[4 + 1], s[4 + 2], s[0]])
        # Initialize only before admission. Missing counters with prior activity require reconciliation.
        with self.db() as db:
            for v in db.scalars(select(Voucher)).all():
                self.initialize_stock(v.id)
