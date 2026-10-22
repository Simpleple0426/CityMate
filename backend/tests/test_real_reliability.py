"""Real MySQL/Redis checks; opt in with the two CITYMATE_TEST_* URLs.

Uses only the guarded citymate_test fixture and its random Redis key prefix.
Process termination targets children created here, never the running demo worker.
"""

import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError
from sqlalchemy import func, select

from citymate.models import Order, Outbox, Voucher
from citymate.runtime import build
from citymate.scripts import ORDER_EVENT
from citymate.worker import Worker

pytestmark = pytest.mark.skipif(
    not (
        os.getenv("CITYMATE_TEST_DATABASE_URL", "").startswith("mysql")
        and os.getenv("CITYMATE_TEST_REDIS_URL")
    ),
    reason="Requires dedicated citymate_test MySQL database and real Redis",
)


def simultaneous(count, action):
    barrier = Barrier(count)

    def run(index):
        barrier.wait(timeout=30)
        return action(index)

    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(run, range(count)))


def assert_stock(platform, expected):
    assert int(platform.r.get(platform.key("stock:v1"))) == expected
    with platform.db() as db:
        assert db.get(Voucher, "v1").stock == expected


def assert_drained(platform):
    assert platform.r.xpending(platform.key("orders"), Worker.group)["pending"] == 0
    with platform.db() as db:
        assert db.scalar(select(func.count()).select_from(Outbox).where(Outbox.done == 0)) == 0


def child_worker(settings, checkpoint=None, crash_phase=None):
    platform, engine = build(settings)
    try:
        if crash_phase:
            original = platform.process_order

            def stop_at_checkpoint(payload):
                if crash_phase == "after_commit":
                    original(payload)
                checkpoint.set()
                # The parent kills this child while its Stream record remains pending.
                multiprocessing.Event().wait(120)
                raise RuntimeError("Parent did not terminate the checkpointed worker")

            platform.process_order = stop_at_checkpoint
        Worker(platform).tick(block=1, reclaim_ms=0)
    finally:
        platform.close()
        platform.r.close()
        engine.dispose()


@pytest.mark.parametrize("round_number", range(3))
def test_concurrent_http_claims_finish_with_ten_orders(client, platform, round_number):
    headers = []
    for index in range(25):
        phone = f"1380000{index:04d}"
        anonymous, code = platform.code(phone)
        session, _ = platform.login(phone, code["demo_code"], anonymous)
        headers.append({"Cookie": f"citymate_session={session}"})

    responses = simultaneous(
        25, lambda index: client.post("/vouchers/v1/claim", headers=headers[index])
    )
    accepted = [response.json() for response in responses if response.status_code == 202]
    assert len(accepted) == 10
    assert sum(response.status_code == 409 for response in responses) == 15
    assert len({item["order_id"] for item in accepted}) == 10
    assert platform.r.xlen(platform.key("orders")) == 10
    Worker(platform).tick(block=1)
    with platform.db() as db:
        orders = db.scalars(select(Order)).all()
        assert len(orders) == 10
        assert len({order.user_id for order in orders}) == 10
        assert all(order.status == "ready" for order in orders)
    assert_stock(platform, 0)
    assert_drained(platform)


def test_simultaneous_duplicate_claims_and_deliveries(platform):
    results = simultaneous(25, lambda _: platform.claim("u0", "v1"))
    assert len({result["order_id"] for result in results}) == 1
    assert sum(not result["replayed"] for result in results) == 1
    assert platform.r.xlen(platform.key("orders")) == 1
    payload = platform.r.xrange(platform.key("orders"))[0][1]
    simultaneous(12, lambda _: platform.process_order(payload))
    Worker(platform).tick(block=1)
    with platform.db() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 1
    assert_stock(platform, 9)
    assert_drained(platform)


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
def test_terminated_worker_is_recovered_by_new_process(platform, phase):
    order_id = platform.claim("u0", "v1")["order_id"]
    settings = replace(platform.cfg, redis_url=os.environ["CITYMATE_TEST_REDIS_URL"])
    context = multiprocessing.get_context("spawn")
    checkpoint = context.Event()
    child = context.Process(target=child_worker, args=(settings, checkpoint, phase))
    child.start()
    try:
        assert checkpoint.wait(timeout=30), "Worker did not reach crash checkpoint"
        assert platform.r.xpending(platform.key("orders"), Worker.group)["pending"] == 1
        with platform.db() as db:
            assert db.scalar(select(func.count()).select_from(Order)) == (
                1 if phase == "after_commit" else 0
            )
            assert db.get(Voucher, "v1").stock == (9 if phase == "after_commit" else 10)
    finally:
        child.terminate()
        child.join(timeout=10)
        if child.is_alive():
            child.kill()
            child.join(timeout=10)
    assert child.exitcode is not None and child.exitcode != 0
    replacement = context.Process(target=child_worker, args=(settings,))
    replacement.start()
    try:
        replacement.join(timeout=30)
        assert replacement.exitcode == 0, "Replacement worker failed or timed out"
    finally:
        if replacement.is_alive():
            replacement.kill()
            replacement.join(timeout=10)
    assert platform.order("u0", order_id)["status"] == "ready"
    with platform.db() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 1
    assert_stock(platform, 9)
    assert_drained(platform)


def test_transaction_failure_rolls_back_and_pending_retries(platform, monkeypatch):
    order_id = platform.claim("u0", "v1")["order_id"]
    worker = Worker(platform)

    def fail_before_commit(*_):
        raise RuntimeError("Injected failure after SQL stock update, before commit")

    with monkeypatch.context() as patch:
        patch.setattr(platform, "emit", fail_before_commit)
        worker.tick(block=1)
    with platform.db() as db:
        assert db.get(Voucher, "v1").stock == 10
        assert db.scalar(select(func.count()).select_from(Order)) == 0
        assert db.scalar(select(func.count()).select_from(Outbox)) == 0
    assert int(platform.r.get(platform.key("stock:v1"))) == 9
    assert platform.r.xpending(worker.stream, worker.group)["pending"] == 1
    worker.tick(block=1)
    assert platform.order("u0", order_id)["status"] == "ready"
    assert_stock(platform, 9)
    assert_drained(platform)


def test_outbox_retries_after_redis_applied_event_but_reply_was_lost(platform, monkeypatch):
    order_id = platform.claim("u0", "v1")["order_id"]
    Worker(platform).tick(block=1)
    platform.cancel_order("u0", order_id)
    original_eval = platform.r.eval

    def apply_then_disconnect(script, *args):
        result = original_eval(script, *args)
        if script == ORDER_EVENT:
            raise ConnectionError("Injected lost reply after Redis committed the event")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(platform.r, "eval", apply_then_disconnect)
        with pytest.raises(ConnectionError):
            platform.dispatch()
    assert_stock(platform, 10)
    with platform.db() as db:
        assert db.scalar(select(func.count()).select_from(Outbox).where(Outbox.done == 0)) == 1
    platform.dispatch()
    platform.dispatch()
    assert_stock(platform, 10)
    assert not platform.r.hget(platform.key("buyers:v1"), "u0")
    assert platform.r.hget(platform.key("order:" + order_id), "status") == "cancelled"
    assert_drained(platform)


def test_concurrent_cancel_restores_stock_once_and_allows_reclaim(platform):
    order_id = platform.claim("u0", "v1")["order_id"]
    Worker(platform).tick(block=1)
    simultaneous(12, lambda _: platform.cancel_order("u0", order_id))
    simultaneous(4, lambda _: platform.dispatch())
    assert_stock(platform, 10)
    result = platform.claim("u0", "v1")
    assert result["order_id"] != order_id
    Worker(platform).tick(block=1)
    assert platform.order("u0", order_id)["status"] == "cancelled"
    assert platform.order("u0", result["order_id"])["status"] == "ready"
    assert_stock(platform, 9)
    assert_drained(platform)


def test_concurrent_approval_cannot_overbook(platform):
    slot = platform.slots("s1")[0]["label"]
    drafts = [platform.draft_appointment(f"u{i}", "s1", slot, 8) for i in range(2)]
    for index, draft in enumerate(drafts):
        platform.confirm_appointment(f"u{index}", draft["id"])

    def approve(index):
        try:
            return platform.review(drafts[index]["id"], True, "")["status"]
        except HTTPException as exc:
            assert exc.status_code == 409
            return "capacity_rejected"

    assert sorted(simultaneous(2, approve)) == ["approved", "capacity_rejected"]
    assert platform.slots("s1")[0]["seats"] == 4
