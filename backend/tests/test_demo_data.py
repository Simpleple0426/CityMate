import pytest
from sqlalchemy import select, func
from citymate.demo_data import seed_rich
from citymate.models import Shop, Voucher, User, Slot, Appointment, Note, Like, Follow, Checkin


def test_rich_seed_is_repeatable_and_preserves_activity(platform):
    p = platform
    counts = seed_rich(p)
    assert counts["cm_shops"] == 16
    assert counts["cm_notes"] == 24
    assert counts["cm_users"] == 12
    with p.db.begin() as db:
        db.get(User, "demo-rich-user-01").nickname = "Edited nickname"
        db.get(Shop, "demo-shop-01").longitude = 121.5
        db.get(Voucher, "demo-voucher-01").stock -= 1
        approved = db.get(Appointment, "demo-appointment-05")
        slot_key = (approved.shop_id, approved.slot)
        seats = db.get(Slot, slot_key).seats
    stock_key = p.key("stock:demo-voucher-01")
    p.r.decr(stock_key)
    stock = p.r.get(stock_key)
    assert seed_rich(p) == {}
    with p.db() as db:
        assert db.get(User, "demo-rich-user-01").nickname == "Edited nickname"
        assert db.get(Voucher, "demo-voucher-01").stock == 29
        assert db.get(Slot, slot_key).seats == seats
        assert db.scalar(select(func.count()).select_from(Note)) == 24
        assert db.scalar(select(func.count()).select_from(Appointment)) == 8
    assert p.r.get(stock_key) == stock
    assert len(p.feed("demo-rich-user-01")["items"]) > 0
    assert len(p.ranking()) >= 12
    assert p.shops(longitude=121.5, latitude=31.175, radius=1)[0]["id"] == "demo-shop-01"
    assert p.note("demo-note-01", "u0")["likes"] > 0


def test_rich_seed_refuses_non_demo_and_phone_collision(platform):
    p = platform
    p.cfg.demo = False
    with pytest.raises(RuntimeError):
        seed_rich(p)
    p.cfg.demo = True
    with p.db.begin() as db:
        db.add(User(id="existing-owner", phone="13910000001", nickname="Existing user"))
    with pytest.raises(ValueError):
        seed_rich(p)
    with p.db() as db:
        assert db.get(Shop, "demo-shop-01") is None
        assert db.get(User, "existing-owner").nickname == "Existing user"
