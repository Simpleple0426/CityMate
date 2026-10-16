"""Real-provider evaluation with isolated business data and explicit stack coverage."""
import argparse
import asyncio
from contextlib import AsyncExitStack
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import traceback
from unittest.mock import patch

from dotenv import load_dotenv
from openai import AsyncOpenAI
from openai.resources.chat.completions import AsyncCompletions
from openai.resources.embeddings import AsyncEmbeddings

from evaluation.live_cases import CASES

ROOT = Path(__file__).resolve().parents[1]


def check_turn(expected, snapshot, response, traces):
    checks = []
    def check(name, actual, wanted):
        checks.append({"check": name, "expected": wanted, "actual": actual, "passed": actual == wanted})
    for key, value in expected.get("slots", {}).items():
        check("slot." + key, snapshot["requirements"]["slots"].get(key), value)
    for key in expected.get("absent", []):
        check("absent." + key, key in snapshot["requirements"]["slots"], False)
    if "ambiguous" in expected:
        check("ambiguous", bool(snapshot["requirements"].get("ambiguities")), expected["ambiguous"])
    if "candidates" in expected:
        # Independent DB inspection checks state, not whether the model communicated it correctly.
        check("candidates", snapshot["candidates"], expected["candidates"])
    if "applications" in expected:
        check("applications", len(snapshot["applications"]), expected["applications"])
    if "draft" in expected:
        draft = snapshot["draft"] or {}
        check("draft.target", draft.get("target_id"), expected["draft"])
        check("draft.status", draft.get("status"), "awaiting_confirmation")
        check("draft.displayed", bool(draft.get("id") and draft["id"] in response.get("response", "")), True)
    if expected.get("no_draft"):
        check("no_draft", snapshot["draft"], None)
    for name in expected.get("tools", []):
        check("tool." + name, name in response.get("tools_used", []), True)
    if "agent" in expected:
        check("agent", response.get("agent_type"), expected["agent"])
    if "assessment" in expected:
        evidence = [t.get("evidence", {}) for t in traces if t.get("tool_name") == "assess_free_transfer"]
        check("assessment", evidence[-1].get("status") if evidence else None, expected["assessment"])
    check("response.nonempty", bool(response.get("response", "").strip()), True)
    return checks


async def run(args):
    selected = [case for case in CASES if not args.case or case['id'] in args.case][:args.limit]
    if not selected or args.limit < 1 or args.repeats < 1 or args.max_calls < 1:
        raise ValueError("Select at least one known case and use positive limits")
    load_dotenv(ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not configured")
    cfg = {"api_key": os.environ["OPENAI_API_KEY"], "base_url": os.getenv("OPENAI_BASE_URL") or None}
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "model": model, "mode": args.mode,
              "skills": not args.no_skills, "cases": [], "calls": [], "status": "running",
              "scope": "人工回归集；程序校验状态与工具调用，回复质量仍需人工审阅；不代表泛化能力"}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    folder = tempfile.mkdtemp(prefix="live-state-", dir=output.parent)
    report["state_directory"] = str(Path(folder).resolve())
    current_case = ContextVar("evaluation_case", default="preflight")
    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    original = AsyncCompletions.create
    original_embeddings = AsyncEmbeddings.create
    async def measured(client, *a, **kw):
        if len(report["calls"]) >= args.max_calls:
            raise RuntimeError("evaluation model-call budget exhausted")
        embedding = isinstance(client, AsyncEmbeddings)
        entry = {"model": kw.get("model"), "kind": "embedding" if embedding else "chat", "case": current_case.get()}
        report["calls"].append(entry)
        started = time.monotonic()
        try:
            result = await (original_embeddings if embedding else original)(client, *a, **kw)
            entry["usage"] = result.usage.model_dump() if result.usage else None
            entry["success"] = True
            return result
        except asyncio.CancelledError:
            entry["cancelled"] = True
            raise
        except Exception as exc:
            entry.update(success=False, error_type=type(exc).__name__)
            raise
        finally:
            entry["elapsed_ms"] = round((time.monotonic() - started) * 1000)

    from agents.education_store import EducationStore
    from agents.agent_orchestrator import AgentOrchestrator, Request
    from core.skill_loader import SkillManager
    try:
        save()
        with patch.object(AsyncCompletions, "create", measured), patch.object(AsyncEmbeddings, "create", measured):
            async with AsyncOpenAI(**cfg, timeout=30, max_retries=0) as probe:
                await probe.chat.completions.create(model=model, messages=[{"role": "user", "content": "回复OK"}], max_tokens=32)
            async with AsyncExitStack() as stack:
                api = http = None
                if args.mode == "full":
                    # Never point this runner at an existing production API/database.
                    env = {"COURSEPILOT_EDUCATION_DB": str(Path(folder) / "initial.sqlite3"),
                           "CHROMA_PERSIST_DIRECTORY": str(Path(folder) / "chroma"),
                           "CHROMA_HOST": "127.0.0.1", "CHROMA_PORT": "1",
                           "REDIS_URL": args.redis_url, "PROMETHEUS_PORT": "0",
                           "COURSEPILOT_KNOWLEDGE_TRANSPORT": "mcp",
                           "COURSEPILOT_SKILLS_DIR": str(ROOT / "skills")}
                    stack.enter_context(patch.dict(os.environ, env))
                    import redis.asyncio as redis
                    rc = redis.from_url(args.redis_url)
                    try:
                        await rc.ping()
                    finally:
                        await rc.aclose()
                    import api.main as api
                    await stack.enter_async_context(api.lifespan(api.app))
                    import httpx
                    http = await stack.enter_async_context(httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://eval"))
                    orch = api._orchestrator
                    if args.no_skills:
                        orch.set_skill_manager(None)
                for repeat in range(args.repeats):
                    for case in selected:
                        case_id = f"{case['id']}-{repeat}"
                        report["current_case"] = case_id
                        current_case.set(case_id)
                        store = EducationStore(Path(folder) / f"{case_id}.sqlite3")
                        user = case.get("user", "student_demo")
                        conv = f"live-{time.time_ns()}-{case_id}"
                        if args.mode == "full":
                            isolated_user = conv + "-user"
                            if user == "student_demo":
                                with store.connection() as db:
                                    db.execute("UPDATE enrollments SET user_id=? WHERE user_id='student_demo'", (isolated_user,))
                            user = isolated_user
                        if args.mode == "core":
                            skills = SkillManager(str(ROOT / "skills"))
                            skills.load()
                            orch = AgentOrchestrator(**cfg, model=model, education_store=store, skill_manager=None if args.no_skills else skills)
                        else:
                            orch.education_store = store
                            for agents in orch._pool.values():
                                for agent in agents:
                                    if hasattr(agent, "store"):
                                        agent.store = store
                        history, confirmation, first_confirmation = [], None, None
                        row = {"id": case_id, "turns": [], "passed": False}
                        report["cases"].append(row)
                        calls_before = len(report["calls"])
                        try:
                            for step in case["turns"]:
                                message = step["message"]
                                if message in ("{confirm}", "{first_confirm}"):
                                    message = confirmation if message == "{confirm}" else first_confirmation
                                    if not message:
                                        raise RuntimeError("previous turn did not produce a confirmable draft")
                                started = time.monotonic()
                                if http:
                                    res = await asyncio.wait_for(http.post("/chat", json={"message": message, "user_id": user, "conv_id": conv}), args.turn_timeout)
                                    res.raise_for_status()
                                    response = res.json()
                                else:
                                    result = await asyncio.wait_for(orch.run(Request(message, user, conv, history=history[-10:], context=json.dumps(history[-10:], ensure_ascii=False))), args.turn_timeout)
                                    response = {"response": result.response, "tools_used": result.tools_used,
                                                "agent_type": result.agent_type.value, "request_id": result.request_id}
                                trace = orch.get_tool_trace(response["request_id"]) or {}
                                traces = trace.get("tool_calls", [])
                                draft = store.latest_draft(user, conv)
                                if draft and draft["status"] == "awaiting_confirmation":
                                    confirmation = "确认提交 " + draft["id"]
                                    first_confirmation = first_confirmation or confirmation
                                snapshot = {"requirements": store.requirements(user, conv), "draft": draft,
                                            "applications": store.applications(user)["applications"],
                                            "candidates": [r["id"] for r in store.advise_transfer(user, conv).get("candidates", [])]}
                                checks = check_turn(step["expected"], snapshot, response, traces)
                                row["turns"].append({"message": message, "response": response, "traces": traces, "snapshot": snapshot,
                                                     "elapsed_ms": round((time.monotonic()-started)*1000), "checks": checks})
                                history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": response["response"]}])
                                save()
                                if "draft" in step["expected"] and any(not c["passed"] for c in checks if c["check"].startswith("draft.")):
                                    raise RuntimeError("draft prerequisite failed; dependent confirmations not executed")
                            row["passed"] = all(c["passed"] for t in row["turns"] for c in t["checks"])
                        except Exception as exc:
                            row["error_type"] = type(exc).__name__
                        finally:
                            row["model_calls"] = len(report["calls"]) - calls_before
                            if args.mode == "core":
                                await orch._composer._client.close()
                                await orch._intent_recognizer.client.close()
                        print(case_id, "PASS" if row["passed"] else "FAIL", flush=True)
                        save()
                        if len(report["calls"]) >= args.max_calls:
                            raise RuntimeError("evaluation model-call budget exhausted")
            report["status"] = "completed"
    except Exception as exc:
        report["status"] = "blocked"
        report["error_type"] = type(exc).__name__
        report["error_location"] = [{"file": Path(f.filename).name, "line": f.lineno, "function": f.name} for f in traceback.extract_tb(exc.__traceback__)[-5:]]
        # Never serialize provider exception strings (may contain request details).
    finally:
        rows = report["cases"]
        for row in rows:
            row["model_calls"] = sum(c["case"] == row["id"] for c in report["calls"])
        report["summary"] = {"passed": sum(r["passed"] for r in rows), "executed": len(rows),
            "planned": len(selected)*args.repeats, "model_calls": len(report["calls"]),
            "failed_model_calls": sum(c.get("success") is False for c in report["calls"]),
            "cancelled_model_calls": sum(c.get("cancelled", False) for c in report["calls"]),
            "calls_without_usage": sum(not c.get("usage") for c in report["calls"]),
            "total_tokens": sum((c.get("usage") or {}).get("total_tokens", 0) for c in report["calls"]),
            "cases_without_model_calls": [r["id"] for r in rows if r.get("model_calls") == 0]}
        durations = sorted(t["elapsed_ms"] for row in rows for t in row["turns"])
        report["summary"]["turn_p50_ms"] = durations[len(durations)//2] if durations else None
        report["summary"]["turn_p95_ms"] = durations[min(len(durations)-1, int(len(durations)*0.95))] if durations else None
        report["summary"]["chat_calls"] = sum(c.get("kind") == "chat" for c in report["calls"])
        report["summary"]["embedding_calls"] = sum(c.get("kind") == "embedding" for c in report["calls"])
        save()
    print(json.dumps({"status": report["status"], **report["summary"]}, ensure_ascii=True))
    return report


if __name__ == "__main__":
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["core", "full"], default="core")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--case", action="append", help="Run named cases only; may be repeated")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-calls", type=int, default=120)
    parser.add_argument("--turn-timeout", type=float, default=120)
    parser.add_argument("--redis-url", default="redis://127.0.0.1:16379/15")
    parser.add_argument("--no-skills", action="store_true")
    parser.add_argument("--output", default="data/eval/live-core.json")
    result = asyncio.run(run(parser.parse_args()))
    raise SystemExit(0 if result['status'] == 'completed' and all(row['passed'] for row in result['cases']) else 1)
