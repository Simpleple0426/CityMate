import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select, func, update
from citymate.models import Order, Voucher, Outbox, Slot, utcnow
from citymate.worker import Worker
from .conftest import login
import pytest


def test_login_code_single_use_logout_and_role_boundary(client):
    code = client.post("/auth/code", json={"phone": "13800000000"}).json()["demo_code"]
    body = {"phone": "13800000000", "code": code}
    response = client.post("/auth/login", json=body)
    assert response.status_code == 200
    assert client.post("/auth/login", json=body).status_code == 401
    h = {"Cookie": "citymate_session=" + client.cookies.get("citymate_session")}
    assert client.get("/me", headers=h).json()["id"] == "u0"
    assert client.get("/admin/stats", headers=h).status_code == 403
    assert (
        client.post(
            "/chat", headers=h, json={"message": "你好", "user_id": "demo-admin"}
        ).status_code
        == 422
    )
    assert client.post("/auth/logout", headers=h).status_code == 200
    assert client.get("/me", headers=h).status_code == 401


def test_login_rate_limit_and_production_code_disabled(platform, client):
    assert client.post("/auth/code", json={"phone": "13800000000"}).status_code == 200
    assert client.post("/auth/code", json={"phone": "13800000000"}).status_code == 429
    for _ in range(6):
        assert (
            client.post("/auth/login", json={"phone": "13800000000", "code": "xxxxxx"}).status_code
            == 422
        )
    platform.cfg.demo = False
    assert client.post("/auth/code", json={"phone": "13800000001"}).status_code == 503


def test_negative_cache_and_invalidation(platform):
    for _ in range(2):
        with pytest.raises(HTTPException) as e:
            platform.shop("missing")
        assert e.value.status_code == 404
    assert platform.r.exists(platform.key("shop:missing"))
    original = platform.shop("s1")
    edited = {**original, "name": "更新后的商户"}
    edited.pop("id")
    platform.edit_shop("s1", edited)
    assert platform.shop("s1")["name"] == "更新后的商户"


def test_geo_and_uv_dedup(platform):
    rows = platform.shops(longitude=121.446, latitude=31.207, radius=1)
    assert rows[0]["id"] == "s1"
    assert rows[0]["distance_km"] < 0.1
    platform.shop("s1", "u0")
    platform.shop("s1", "u0")
    keys = list(platform.r.scan_iter(platform.key("uv:s1:*")))
    assert len(keys) == 1 and platform.r.pfcount(keys[0]) == 1


def test_atomic_claim_no_oversell_and_one_per_user(platform):
    def claim(i):
        try:
            return platform.claim(f"u{i}", "v1")
        except HTTPException as e:
            assert e.status_code == 409
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(claim, range(25)))
    accepted = [r for r in results if r]
    assert len(accepted) == 10
    assert len({r["order_id"] for r in accepted}) == 10
    assert int(platform.r.get(platform.key("stock:v1"))) == 0
    records = platform.r.xrange(platform.key("orders"))
    for _, fields in records:
        replay = platform.claim(fields["user_id"], "v1")
        assert replay["replayed"] and replay["order_id"] == fields["order_id"]
    assert platform.r.xlen(platform.key("orders")) == 10


def test_consumer_replay_cancel_and_reclaim(platform):
    result = platform.claim("u0", "v1")
    worker = Worker(platform, "test-one")
    worker.tick(block=1)
    order = platform.order("u0", result["order_id"])
    assert order["status"] == "ready"
    fields = platform.r.xrange(platform.key("orders"))[0][1]
    platform.process_order(fields)
    with platform.db() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 1
        assert db.get(Voucher, "v1").stock == 9
    assert platform.r.xpending(platform.key("orders"), worker.group)["pending"] == 0
    platform.cancel_order("u0", result["order_id"])
    platform.cancel_order("u0", result["order_id"])
    platform.dispatch()
    platform.dispatch()
    assert int(platform.r.get(platform.key("stock:v1"))) == 10
    with platform.db() as db:
        assert db.get(Voucher, "v1").stock == 10
    new = platform.claim("u0", "v1")
    assert new["order_id"] != result["order_id"]


def test_pending_recovered_after_worker_crash(platform):
    result = platform.claim("u0", "v2")
    old = Worker(platform, "abandoned")
    platform.r.xreadgroup(old.group, old.consumer, {old.stream: ">"}, count=10)
    assert platform.r.xpending(old.stream, old.group)["pending"] == 1
    Worker(platform, "replacement").tick(block=1, reclaim_ms=0)
    assert platform.order("u0", result["order_id"])["status"] == "ready"
    assert platform.r.xpending(old.stream, old.group)["pending"] == 0


def test_database_rejection_compensates_reservation(platform):
    result = platform.claim("u0", "v1")
    with platform.db.begin() as db:
        db.get(Voucher, "v1").stock = 0
    Worker(platform).tick(block=1)
    assert platform.order("u0", result["order_id"])["status"] == "rejected"
    assert not platform.r.hget(platform.key("buyers:v1"), "u0")
    assert int(platform.r.get(platform.key("stock:v1"))) == 10


def test_order_ownership(client, platform):
    h = login(client)
    result = platform.claim("u1", "v1")
    assert client.get("/orders/" + result["order_id"], headers=h).status_code == 404
    Worker(platform).tick(block=1)
    assert client.post("/orders/" + result["order_id"] + "/cancel", headers=h).status_code == 404


def test_activity_window_and_missing_stock_fail_closed(platform):
    with platform.db.begin() as db:
        db.get(Voucher, "v1").ends_at = utcnow() - timedelta(seconds=5)
    with pytest.raises(HTTPException) as exc:
        platform.claim("u0", "v1")
    assert exc.value.status_code == 409
    platform.claim("u0", "v2")
    platform.r.delete(platform.key("stock:v2"))
    with pytest.raises(HTTPException) as exc:
        platform.claim("u1", "v2")
    assert exc.value.status_code == 503


def test_appointment_confirmation_ownership_and_capacity(platform):
    slot = platform.slots("s1")[0]["label"]
    first = platform.draft_appointment("u0", "s1", slot, 10)
    second = platform.draft_appointment("u1", "s1", slot, 10)
    with pytest.raises(HTTPException):
        platform.confirm_appointment("u1", first["id"])
    assert platform.confirm_appointment("u0", first["id"])["status"] == "pending_review"
    platform.confirm_appointment("u0", first["id"])
    platform.confirm_appointment("u1", second["id"])
    assert platform.slots("s1")[0]["seats"] == 12
    assert platform.review(first["id"], True, "")["status"] == "approved"
    with pytest.raises(HTTPException):
        platform.review(second["id"], True, "")
    assert platform.slots("s1")[0]["seats"] == 2


def test_community_likes_follows_feed_and_unfollow(platform):
    platform.follow("u0", "u1", True)
    platform.follow("u2", "u1", True)
    assert platform.common("u0", "u2")[0]["id"] == "u1"
    note = platform.create_note("u1", {"title": "探店", "body": "周末吃饭", "shop_id": "s1"})
    platform.dispatch()
    assert platform.feed("u0")["items"][0]["id"] == note["id"]
    platform.like("u0", note["id"], True)
    platform.like("u0", note["id"], True)
    assert platform.note(note["id"], "u0")["likes"] == 1
    assert platform.r.zcard(platform.key("likes:" + note["id"])) == 1
    platform.like("u0", note["id"], False)
    assert platform.note(note["id"], "u0")["likes"] == 0
    platform.follow("u0", "u1", False)
    assert platform.feed("u0")["items"] == []


def test_feed_same_timestamp_cursor_has_no_duplicates(platform):
    from citymate.models import Note

    stamp = utcnow()
    with platform.db.begin() as db:
        db.add_all(
            Note(id=f"n{i:02}", user_id="u1", title="测试", body="内容", created_at=stamp)
            for i in range(24)
        )
    platform.follow("u0", "u1", True)
    first = platform.feed("u0")
    second = platform.feed("u0", first["next_cursor"])
    third = platform.feed("u0", second["next_cursor"])
    ids = [n["id"] for page in [first, second, third] for n in page["items"]]
    assert len(ids) == len(set(ids)) == 24


def test_checkin_idempotent_and_bitmap_recovery(platform):
    one = platform.checkin("u0")
    two = platform.checkin("u0")
    assert one["points"] == two["points"] == 10
    assert two["replayed"] and two["streak"] == 1
    keys = list(platform.r.scan_iter(platform.key("sign:u0:*")))
    platform.r.delete(*keys)
    assert platform.checkin_stats("u0")["month_days"] == 1
    assert platform.ranking()[0]["points"] == 10


def test_upload_validates_content_and_note_images(client):
    h = login(client)
    assert (
        client.post(
            "/uploads", headers=h, files={"file": ("a.png", b"not-an-image", "image/png")}
        ).status_code
        == 400
    )
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), "green").save(buffer, "PNG")
    result = client.post(
        "/uploads", headers=h, files={"file": ("a.png", buffer.getvalue(), "image/png")}
    )
    assert result.status_code == 200
    url = result.json()["url"]
    assert client.get(url).headers["content-type"] == "image/jpeg"
    assert (
        client.post(
            "/notes", headers=h, json={"title": "图文", "body": "内容", "images": [url]}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/notes",
            headers=h,
            json={"title": "图文", "body": "内容", "images": ["/uploads/../../secret"]},
        ).status_code
        == 400
    )


def test_assistant_scoped_memory_and_rules_mode(client, platform):
    h = login(client)
    first = client.post("/chat", headers=h, json={"message": "推荐人均不超过100元的餐厅"})
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["mode"] == "rules"
    assert data["preferences"]["budget"] == "10000"
    second = client.post("/chat", headers=h, json={"message": "再看看", "conv_id": data["conv_id"]})
    assert second.status_code == 200, second.text
    assert second.json()["preferences"]["budget"] == "10000"
    another = login(client, "13800000001")
    other = client.post(
        "/chat", headers=another, json={"message": "你好", "conv_id": data["conv_id"]}
    )
    assert other.json()["preferences"] == {}


def test_admin_approval_api(client, platform):
    admin = login(client, "13900000000")
    ordinary = login(client)
    assert client.get("/admin/appointments", headers=ordinary).status_code == 403
    draft = platform.draft_appointment("u0", "s1", platform.slots("s1")[0]["label"], 2)
    platform.confirm_appointment("u0", draft["id"])
    assert (
        client.post(
            "/admin/appointments/" + draft["id"] + "/review", headers=admin, json={"approve": True}
        ).json()["status"]
        == "approved"
    )
    assert client.get("/metrics", headers=admin).status_code == 200
    assert client.get("/metrics").status_code == 401


def test_admin_create_shop_and_voucher(client, platform):
    from datetime import timezone

    admin = login(client, "13900000000")
    ordinary = login(client)
    shop = {
        "name": "新商户",
        "category": "运动",
        "description": "验证新增商户",
        "address": "演示地址",
        "longitude": 121.44,
        "latitude": 31.21,
        "price_cents": 6000,
        "hours": "10:00–20:00",
    }
    assert client.post("/admin/shops", headers=ordinary, json=shop).status_code == 403
    response = client.post("/admin/shops", headers=admin, json=shop)
    assert response.status_code == 201, response.text
    shop_id = response.json()["id"]
    body = {
        "shop_id": shop_id,
        "title": "新体验券",
        "rules": "演示规则",
        "price_cents": 3000,
        "stock": 2,
        "starts_at": (utcnow() - timedelta(minutes=1)).replace(tzinfo=timezone.utc).isoformat(),
        "ends_at": (utcnow() + timedelta(days=1)).replace(tzinfo=timezone.utc).isoformat(),
    }
    voucher = client.post("/admin/vouchers", headers=admin, json=body)
    assert voucher.status_code == 201, voucher.text
    assert platform.claim("u0", voucher.json()["id"])["status"] == "processing"
    assert (
        client.post(
            "/admin/vouchers", headers=admin, json={**body, "ends_at": body["starts_at"]}
        ).status_code
        == 400
    )


@pytest.mark.parametrize(
    "tool,args", [("my_orders", '{"user_id":"u1"}'), ("claim", '{"voucher_id":"v1"}')]
)
def test_model_cannot_override_identity_or_execute_purchase(client, platform, tool, args):
    from types import SimpleNamespace

    class ToolMessage:
        content = None
        tool_calls = [
            SimpleNamespace(id="call-1", function=SimpleNamespace(name=tool, arguments=args))
        ]

        def model_dump(self, **_):
            return {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": tool, "arguments": args},
                    }
                ],
            }

    class FakeModel:
        calls = 0

        def __init__(self):
            self.chat = SimpleNamespace(completions=self)

        async def create(self, **kwargs):
            self.calls += 1
            response = (
                ToolMessage()
                if self.calls == 1
                else SimpleNamespace(content="请通过订单页操作。", tool_calls=None)
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=response)])

        async def close(self):
            pass

    client.app.state.assistant.client = FakeModel()
    h = login(client)
    response = client.post("/chat", headers=h, json={"message": "查询我的订单"})
    assert response.status_code == 200, response.text
    assert "error" in response.json()["tools"][0]["result"]
    assert platform.r.xlen(platform.key("orders")) == 0
