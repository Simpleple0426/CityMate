"""Bounded real-TCP load experiment; only a NEW citymate_load_<12 hex> database.

Uses a private API process, ordinary Worker loop, Redis DB 15 with a unique prefix,
pre-authenticated synthetic users, and optional real model conversations. Never
clears a database or flushes Redis. The output preserves each request and sample.
"""

import argparse
import asyncio
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import math
import multiprocessing as mp
import os
from pathlib import Path
import re
import secrets
import socket
import time
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url

from citymate.config import Settings
from citymate.models import Base, User, Voucher, Order, Outbox, Appointment, utcnow
from citymate.runtime import build
from citymate.worker import Worker


def percentile(values, p):
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)] if values else None


def distribution(values):
    return {
        "count": len(values),
        "p50": percentile(values, 0.5),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values) if values else None,
    }


def validate_target(database_url, redis_url):
    db = make_url(database_url)
    if (
        db.get_backend_name() != "mysql"
        or db.host not in {"127.0.0.1", "localhost"}
        or not re.fullmatch(r"citymate_load_[a-f0-9]{12}", db.database or "")
    ):
        raise ValueError("A new local citymate_load_<12 hex> MySQL database is required")
    redis = urlparse(redis_url)
    if redis.hostname not in {"localhost", "127.0.0.1"} or redis.path != "/15":
        raise ValueError("Use local Redis DB 15; never point at the business DB")
    return db.database.removeprefix("citymate_load_")


class Inflight:
    """Measure actual server ASGI request lifetimes, including time waiting for IO."""

    def __init__(self, app, counter, run_id):
        self.app, self.counter, self.run_id = app, counter, run_id

    async def __call__(self, scope, receive, send):
        track = scope["type"] == "http" and b"x-load-stage" in dict(scope.get("headers", []))
        if track:
            with self.counter.get_lock():
                self.counter[0] += 1
                self.counter[1] = max(self.counter[1], self.counter[0])
                self.counter[2] += 1

        async def wrapped(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-load-run", self.run_id.encode())
                ]
            await send(message)

        try:
            await self.app(scope, receive, wrapped)
        finally:
            if track:
                with self.counter.get_lock():
                    self.counter[0] -= 1


def serve(cfg, port, counter, run_id):
    import uvicorn
    from citymate.app import create_app

    logging.disable(logging.CRITICAL)
    os.environ["CITYMATE_KNOWLEDGE_MODE"] = "lexical"
    os.environ["CITYMATE_KNOWLEDGE_TRANSPORT"] = "local"
    uvicorn.run(
        Inflight(create_app(cfg), counter, run_id),
        host="127.0.0.1",
        port=port,
        access_log=False,
        log_level="critical",
    )


def consume(cfg, stop):
    logging.disable(logging.CRITICAL)
    p, engine = build(replace(cfg, api_key=""))
    try:
        worker = Worker(p)
        while not stop.is_set():
            worker.tick()  # Same batch/reclaim/block settings as the ordinary worker.
            stop.wait(0.2)
    finally:
        p.close()
        p.r.close()
        engine.dispose()


class Experiment:
    def __init__(self, args):
        self.args = args
        settings = Settings()
        self.secret = settings.api_key
        if args.live_agent and not settings.api_key:
            raise ValueError("Live agent evaluation requires a configured model key")
        db_url = os.environ["CITYMATE_LOAD_DATABASE_URL"]
        redis_url = os.environ["CITYMATE_LOAD_REDIS_URL"]
        self.run_id = validate_target(db_url, redis_url)
        self.cfg = replace(
            settings,
            database_url=db_url,
            redis_url=redis_url,
            api_key=settings.api_key if args.live_agent else "",
            demo=True,
            prefix="load:{" + self.run_id + "}:",
            uploads=args.output.parent / (args.output.stem + "-uploads"),
        )
        self.p, self.engine = build(self.cfg)
        if inspect(self.engine).get_table_names():
            raise ValueError(
                "Refusing non-empty benchmark database; use a freshly created database"
            )
        if next(self.p.r.scan_iter(self.cfg.prefix + "*"), None):
            raise ValueError("Refusing an existing Redis run prefix")
        self.context = mp.get_context("spawn")
        self.counter = self.context.Array("q", [0, 0, 0])
        self.stop = self.context.Event()
        self.children = []
        self.origin = time.monotonic()
        self.report = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "model": settings.model if args.live_agent else None,
            "deployment": {
                "api_processes": 1,
                "worker_processes": 1,
                "transport": "real HTTP/TCP loopback",
                "knowledge": "local lexical",
                "database": make_url(db_url).database,
                "redis_db": 15,
                "same_host_generator": True,
                "login_outside_timing": True,
                "sql_pool_per_process": "SQLAlchemy defaults: pool_size=5, max_overflow=10",
                "worker_pause_seconds": 0.2,
            },
            "settings": {
                "closed_loop_seconds": args.seconds,
                "soak_seconds": args.soak_seconds,
                "soak_rate_cap": 10,
                "max_requests_per_stage": args.max_requests,
                "queue_guard": args.queue_guard,
                "drain_timeout_s": args.drain_timeout,
                "claim_timeout_s": 15,
                "agent_http_timeout_s": 180,
                "agent_requests_retried_by_harness": False,
            },
            "source_sha256": {
                str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [*Path("citymate").rglob("*.py"), Path(__file__)]
            },
            "business": [],
            "agent": [],
            "errors": [],
        }
        if args.host_info:
            self.report["host"] = json.loads(args.host_info.read_text(encoding="utf-8"))

    def ms(self):
        return round((time.monotonic() - self.origin) * 1000, 3)

    def save(self):
        data = json.dumps(self.report, ensure_ascii=False, indent=2)
        if self.secret and self.secret in data:
            raise RuntimeError("Refusing to write credential")
        self.args.output.write_text(data + "\n", encoding="utf-8")

    def setup(self):
        Base.metadata.create_all(self.engine)
        self.p.seed()
        self.sessions = []
        with self.p.db.begin() as db:
            db.add_all(
                User(id=f"load-u{i}", phone=f"188{i:08d}", nickname=f"Load {i}")
                for i in range(self.args.max_requests)
            )
        for offset in range(0, self.args.max_requests, 250):
            with self.p.r.pipeline() as pipe:
                for i in range(offset, min(offset + 250, self.args.max_requests)):
                    token = secrets.token_urlsafe(32)
                    self.sessions.append(token)
                    key = self.p.session_key(token)
                    pipe.hset(key, mapping={"user": json.dumps({"id": f"load-u{i}"})})
                    pipe.expire(key, 7200)
                pipe.execute()
        with self.p.db() as db:
            self.report["deployment"]["mysql_version"] = db.scalar(text("SELECT VERSION()"))
        self.report["deployment"]["redis_version"] = self.p.r.info("server")["redis_version"]
        self.report["deployment"]["redis_appendfsync"] = self.p.r.config_get("appendfsync")[
            "appendfsync"
        ]
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        self.report["deployment"]["port"] = port
        for target, params in [
            (serve, (self.cfg, port, self.counter, self.run_id)),
            (consume, (self.cfg, self.stop)),
        ]:
            process = self.context.Process(target=target, args=params)
            process.start()
            self.children.append(process)
        with httpx.Client(timeout=2, trust_env=False) as http:
            for _ in range(60):
                if not all(p.is_alive() for p in self.children):
                    raise RuntimeError("Benchmark child process exited during startup")
                try:
                    health = http.get(self.url + "/health")
                    if (
                        health.status_code == 200
                        and health.headers.get("x-load-run") == self.run_id
                        and health.json()["worker_online"]
                    ):
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                raise RuntimeError("Private API did not become healthy")
            http.get(self.url + "/shops")  # Untimed startup warm-up, no admission.
        self.save()

    def new_voucher(self, label, stock):
        with self.p.db.begin() as db:
            db.add(
                Voucher(
                    id=label,
                    shop_id="s1",
                    title="Load test",
                    rules="Synthetic isolated test",
                    price_cents=1000,
                    stock=stock,
                    starts_at=utcnow() - timedelta(hours=1),
                    ends_at=utcnow() + timedelta(hours=4),
                )
            )
        self.p.initialize_stock(label)

    def sample(self, voucher):
        group = next(
            g for g in self.p.r.xinfo_groups(self.p.key("orders")) if g["name"] == Worker.group
        )
        if group.get("lag") is None:
            raise RuntimeError("Stream lag is unknown; cannot assert queue drainage")
        with self.p.db() as db:
            rows = list(
                db.execute(
                    select(Order.id, Order.status, Order.user_id).where(Order.voucher_id == voucher)
                )
            )
            outbox = db.scalar(select(func.count()).select_from(Outbox).where(Outbox.done == 0))
        statuses = self.p.r.pipeline(transaction=False)
        for oid, _, _ in rows:
            statuses.hget(self.p.key("order:" + oid), "status")
        redis_states = statuses.execute()
        observed = self.ms()
        completed = [
            oid
            for (oid, status, _), cached in zip(rows, redis_states)
            if status == "ready" and cached == "ready"
        ]
        return {
            "at_ms": observed,
            "lag": group.get("lag"),
            "pending": group["pending"],
            "backlog": (group.get("lag") or 0) + group["pending"],
            "outbox_undelivered": outbox,
            "sql_orders": len(rows),
            "ready_both": len(completed),
        }, completed

    async def business(
        self,
        label,
        concurrency,
        seconds,
        stock=5000,
        request_limit=None,
        duplicate=False,
        rate=None,
    ):
        self.new_voucher(label, stock)
        stage = {
            "label": label,
            "concurrency_limit": concurrency,
            "target_seconds": seconds,
            "rate_cap": rate,
            "initial_stock": stock,
            "requests": [],
            "samples": [],
            "completion_observed_ms": {},
            "stop_reason": "duration" if seconds is not None else "finite_batch",
            "observation": "SQL ready and Redis ready first observed by nominal 1-second poll; latency is an upper bound, not exact commit time",
        }
        self.report["business"].append(stage)
        with self.counter.get_lock():
            self.counter[:] = [0, 0, 0]
        count = active = peak = 0
        stopping = False
        monitoring = True
        next_slot = 0.0
        started = time.monotonic()
        stream_start = self.p.r.xlen(self.p.key("orders"))
        stage["started_ms"] = self.ms()
        limit = request_limit or self.args.max_requests

        async def observe():
            nonlocal stopping
            while monitoring:
                sample, completed = await asyncio.to_thread(self.sample, label)
                stage["samples"].append(sample)
                for oid in completed:
                    stage["completion_observed_ms"].setdefault(oid, sample["at_ms"])
                if sample["backlog"] > self.args.queue_guard:
                    stopping = True
                    stage["stop_reason"] = "backlog_guard"
                await asyncio.sleep(1)

        async def sender(http):
            nonlocal count, active, peak, next_slot
            while not stopping and (seconds is None or time.monotonic() - started < seconds):
                if count >= limit:
                    if request_limit is None:
                        stage["stop_reason"] = "request_guard"
                    return
                if rate:
                    now = time.monotonic()
                    due = max(now, next_slot)
                    next_slot = due + 1 / rate
                    await asyncio.sleep(max(0, due - now))
                    if stopping or (seconds is not None and time.monotonic() - started >= seconds):
                        return
                    if count >= limit:
                        stage["stop_reason"] = "request_guard"
                        return
                i = count
                count += 1
                user = 0 if duplicate else i
                row = {"index": i, "user_id": f"load-u{user}", "start_ms": self.ms()}
                active += 1
                peak = max(peak, active)
                try:
                    response = await http.post(
                        f"/vouchers/{label}/claim",
                        headers={
                            "Cookie": "citymate_session=" + self.sessions[user],
                            "X-Load-Stage": label,
                        },
                    )
                    row["status"] = response.status_code
                    data = response.json()
                    if response.status_code == 202:
                        row.update(order_id=data["order_id"], replayed=data["replayed"])
                    else:
                        row["detail"] = data.get("detail")
                except Exception as exc:
                    row.update(status=0, exception_type=type(exc).__name__)
                finally:
                    row["end_ms"] = self.ms()
                    row["latency_ms"] = round(row["end_ms"] - row["start_ms"], 3)
                    active -= 1
                    stage["requests"].append(row)

        monitor = asyncio.create_task(observe())
        async with httpx.AsyncClient(
            base_url=self.url,
            headers={"X-CityMate-Request": "1"},
            timeout=15,
            trust_env=False,
            limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
        ) as http:
            await asyncio.gather(*(sender(http) for _ in range(concurrency)))
        ended = time.monotonic()
        stage["requests_ended_ms"] = self.ms()
        stage["elapsed_s"] = round(ended - started, 3)
        with self.counter.get_lock():
            stage["server_inflight_peak"], stage["server_requests"] = (
                self.counter[1],
                self.counter[2],
            )
        stage["client_inflight_peak"] = peak
        accepted = {r["order_id"] for r in stage["requests"] if r["status"] == 202}
        deadline = time.monotonic() + self.args.drain_timeout
        while time.monotonic() < deadline:
            if monitor.done():
                await monitor  # Propagate observer failures instead of claiming completion.
            if (
                stage["samples"]
                and accepted <= stage["completion_observed_ms"].keys()
                and not stage["samples"][-1]["backlog"]
                and not stage["samples"][-1]["outbox_undelivered"]
            ):
                break
            await asyncio.sleep(0.25)
        monitoring = False
        await monitor
        self.audit(stage, accepted, stream_start)
        counts = Counter(r["status"] for r in stage["requests"])
        expected_409 = label == "flash"
        bad = sum(
            n
            for status, n in counts.items()
            if status != 202 and not (status == 409 and expected_409)
        )
        stage["summary"] = {
            "requests": len(stage["requests"]),
            "http_statuses": dict(counts),
            "http_qps": len(stage["requests"]) / stage["elapsed_s"],
            "accepted_response_qps": counts[202] / stage["elapsed_s"],
            "new_orders": len(accepted),
            "unexpected_errors": bad,
            "unexpected_error_rate": bad / max(1, len(stage["requests"])),
            "http_latency_ms": distribution([r["latency_ms"] for r in stage["requests"]]),
            "accepted_latency_ms": distribution(
                [r["latency_ms"] for r in stage["requests"] if r["status"] == 202]
            ),
            "peak_backlog": max(s["backlog"] for s in stage["samples"]),
            "peak_outbox": max(s["outbox_undelivered"] for s in stage["samples"]),
            "drain_s": max(
                0,
                (
                    max(
                        stage["completion_observed_ms"].values(), default=stage["requests_ended_ms"]
                    )
                    - stage["requests_ended_ms"]
                )
                / 1000,
            ),
        }
        first_start = {}
        for r in stage["requests"]:
            if r.get("order_id"):
                first_start[r["order_id"]] = min(
                    r["start_ms"], first_start.get(r["order_id"], float("inf"))
                )
        latency = [
            stage["completion_observed_ms"][oid] - first_start[oid]
            for oid in accepted
            if oid in stage["completion_observed_ms"]
        ]
        stage["summary"]["completion_observed_latency_ms"] = distribution(latency)
        end_ms = max(stage["completion_observed_ms"].values(), default=stage["requests_ended_ms"])
        stage["summary"]["new_order_completion_qps_including_drain"] = len(latency) / max(
            0.001, (end_ms - stage["started_ms"]) / 1000
        )
        self.save()
        print(
            "BUSINESS",
            label,
            json.dumps(stage["summary"], ensure_ascii=False),
            "stop=" + stage["stop_reason"],
            flush=True,
        )
        if not all(stage["integrity"].values()):
            raise RuntimeError("Business integrity audit failed; inspect report")

    def audit(self, stage, accepted, stream_start):
        label = stage["label"]
        with self.p.db() as db:
            rows = list(db.scalars(select(Order).where(Order.voucher_id == label)))
            stock = db.get(Voucher, label).stock
        redis_stock = int(self.p.r.get(self.p.key("stock:" + label)))
        ids = {o.id for o in rows}
        expected_users = {
            r["order_id"]: r["user_id"] for r in stage["requests"] if r.get("order_id")
        }
        final = stage["samples"][-1]
        stage["integrity"] = {
            "some_orders_completed": bool(rows),
            "expected_burst_orders": (
                len(rows) == (10 if label == "flash" else 1)
                if label in {"flash", "duplicate"}
                else True
            ),
            "accepted_equals_sql_ids": accepted == ids,
            "all_orders_ready": all(o.status == "ready" for o in rows),
            "no_duplicate_users": len({o.user_id for o in rows}) == len(rows),
            "owners_match_requests": all(expected_users.get(o.id) == o.user_id for o in rows),
            "no_oversell": len(rows) <= stage["initial_stock"] and min(stock, redis_stock) >= 0,
            "stock_conservation": stock == redis_stock == stage["initial_stock"] - len(rows),
            "stream_only_once": self.p.r.xlen(self.p.key("orders")) - stream_start == len(rows),
            "queue_drained": final["backlog"] == 0 and final["outbox_undelivered"] == 0,
            "all_completions_observed": accepted <= stage["completion_observed_ms"].keys(),
        }
        stage["final_state"] = {
            "sql_orders": len(rows),
            "sql_stock": stock,
            "redis_stock": redis_stock,
            "backlog": final["backlog"],
            "outbox": final["outbox_undelivered"],
        }

    async def agent(self, concurrency):
        stage = {
            "concurrency_limit": concurrency,
            "transactions": [],
            "scenario_mix": "2 merchant preference follow-ups, 2 booking with explicit confirmation, 2 policy questions",
        }
        self.report["agent"].append(stage)
        gate = asyncio.Semaphore(concurrency)
        with self.counter.get_lock():
            self.counter[:] = [0, 0, 0]
        active = peak = 0
        started = time.monotonic()
        slot = self.p.slots("s3")[0]["label"]

        async with httpx.AsyncClient(
            base_url=self.url,
            headers={"X-CityMate-Request": "1"},
            timeout=180,
            trust_env=False,
            limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
        ) as http:

            async def transaction(index):
                nonlocal active, peak
                async with gate:
                    active += 1
                    peak = max(peak, active)
                    kind = ("discovery", "booking", "policy")[index % 3]
                    user = concurrency * 10 + index
                    item = {
                        "index": index,
                        "kind": kind,
                        "start_ms": self.ms(),
                        "turns": [],
                        "checks": {},
                    }
                    conv = None

                    async def turn(message):
                        nonlocal conv
                        row = {"message": message, "start_ms": self.ms()}
                        try:
                            response = await http.post(
                                "/chat",
                                headers={
                                    "Cookie": "citymate_session=" + self.sessions[user],
                                    "X-Load-Stage": f"agent-{concurrency}",
                                },
                                json={"message": message, "conv_id": conv},
                            )
                            row["http_status"] = response.status_code
                            result = response.json()
                            row["result"] = result
                            if response.status_code != 200:
                                raise RuntimeError("Chat did not complete")
                            conv = result["conv_id"]
                            return result
                        finally:
                            row["end_ms"] = self.ms()
                            row["latency_ms"] = row["end_ms"] - row["start_ms"]
                            item["turns"].append(row)

                    try:
                        if kind == "discovery":
                            await turn("推荐人均不超过100元的美食餐厅")
                            result = await turn("改成推荐咖啡店，人均不超过50元")
                            successful = [
                                t
                                for t in result["tools"]
                                if t["tool"] == "search_shops" and isinstance(t["result"], list)
                            ]
                            item["checks"]["category_and_budget"] = any(
                                t.get("arguments", {}).get("category") == "咖啡"
                                and t.get("arguments", {}).get("budget") == 5000
                                for t in successful
                            )
                        elif kind == "booking":
                            await turn("我想预约青岚攀岩（s3）")
                            result = await turn(f"请选择{slot}，2个人，生成预约草稿")
                            drafts = [
                                t["result"]
                                for t in result["tools"]
                                if t["tool"] == "prepare_appointment" and "id" in t["result"]
                            ]
                            item["checks"]["draft_created"] = bool(drafts)
                            if drafts:
                                draft = drafts[-1]
                                item["checks"]["draft_fields"] = (
                                    draft["shop_id"] == "s3"
                                    and draft["slot"] == slot
                                    and draft["party_size"] == 2
                                )
                                confirmed = await turn("确认预约 " + draft["id"])
                                with self.p.db() as db:
                                    saved = db.get(Appointment, draft["id"])
                                    item["checks"]["owned_pending_review"] = (
                                        saved.user_id == f"load-u{user}"
                                        and saved.status == "pending_review"
                                    )
                                item["checks"]["confirmation_has_no_model_call"] = (
                                    confirmed["model_calls"] == 0
                                )
                        else:
                            result = await turn("请检索平台政策，预约草稿的有效期是多久？")
                            item["checks"]["source_and_key_fact"] = any(
                                s.get("source") == "citymate/预约规则.txt"
                                for s in result["sources"]
                            ) and ("15" in result["response"] or "十五" in result["response"])
                        item["checks"]["real_model_used"] = any(
                            t.get("result", {}).get("model_calls", 0) > 0 for t in item["turns"]
                        )
                    except Exception as exc:
                        item["exception_type"] = type(exc).__name__
                    finally:
                        item["end_ms"] = self.ms()
                        item["latency_ms"] = item["end_ms"] - item["start_ms"]
                        item["passed"] = (
                            bool(item["checks"])
                            and all(item["checks"].values())
                            and "exception_type" not in item
                        )
                        active -= 1
                        stage["transactions"].append(item)
                        self.save()
                        print(
                            "AGENT",
                            concurrency,
                            index,
                            kind,
                            "PASS" if item["passed"] else "FAIL",
                            flush=True,
                        )

            await asyncio.gather(*(transaction(i) for i in range(6)))
        stage["elapsed_s"] = time.monotonic() - started
        stage["transaction_inflight_peak"] = peak
        stage["server_http_inflight_peak"] = self.counter[1]
        turns = [t for x in stage["transactions"] for t in x["turns"]]
        stage["summary"] = {
            "transactions": 6,
            "passed": sum(x["passed"] for x in stage["transactions"]),
            "task_completion_rate": sum(x["passed"] for x in stage["transactions"]) / 6,
            "task_latency_ms": distribution([x["latency_ms"] for x in stage["transactions"]]),
            "http_latency_ms": distribution([t["latency_ms"] for t in turns]),
            "http_statuses": dict(Counter(t.get("http_status", 0) for t in turns)),
            "completed_tasks_per_minute": sum(x["passed"] for x in stage["transactions"])
            * 60
            / stage["elapsed_s"],
            "model_calls": sum(t.get("result", {}).get("model_calls", 0) for t in turns),
            "reported_tokens": sum(
                (t.get("result", {}).get("token_usage") or {}).get("total_tokens", 0) for t in turns
            ),
        }
        self.save()
        print("AGENT SUMMARY", concurrency, json.dumps(stage["summary"]), flush=True)

    async def run(self):
        await self.business("flash", 100, None, stock=10, request_limit=100)
        await self.business("duplicate", 50, None, stock=10, request_limit=50, duplicate=True)
        for concurrency in [1, 10, 25, 50]:
            await self.business(
                f"step-{concurrency}", concurrency, self.args.seconds, stock=self.args.max_requests
            )
        await self.business(
            "soak", 5, self.args.soak_seconds, stock=self.args.max_requests, rate=10
        )
        if self.args.live_agent:
            for concurrency in [1, 2, 4]:
                await self.agent(concurrency)

    def close(self):
        self.stop.set()
        for child in reversed(self.children):
            child.join(timeout=3)
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
            if child.is_alive():
                child.kill()
                child.join(timeout=5)
        self.p.close()
        self.p.r.close()
        self.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--host-info", type=Path)
    parser.add_argument("--live-agent", action="store_true")
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--soak-seconds", type=int, default=120)
    parser.add_argument("--max-requests", type=int, default=5000)
    parser.add_argument("--queue-guard", type=int, default=1000)
    parser.add_argument("--drain-timeout", type=int, default=180)
    args = parser.parse_args()
    if args.output.exists() or not (
        1 <= args.seconds <= 120
        and 1 <= args.soak_seconds <= 300
        and 100 <= args.max_requests <= 10000
        and 100 <= args.queue_guard <= 5000
        and 10 <= args.drain_timeout <= 300
    ):
        parser.error("Use a new report path and bounded load settings")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    experiment = Experiment(args)
    try:
        experiment.setup()
        asyncio.run(experiment.run())
        experiment.report["execution_complete"] = True
    except Exception as exc:
        experiment.report["errors"].append(type(exc).__name__)
        experiment.report["execution_complete"] = False
        print("Experiment stopped:", type(exc).__name__, flush=True)
    finally:
        experiment.close()
        experiment.report["finished_at"] = datetime.now(timezone.utc).isoformat()
        experiment.save()
    return 0 if experiment.report["execution_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
