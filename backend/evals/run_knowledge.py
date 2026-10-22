"""Real embeddings + MCP + optional live-model HTTP evaluation on isolated data.

Run from backend: python -m evals.run_knowledge --live --output logs/knowledge-run.json
The live flag makes billable model calls. Existing reports are never overwritten.
"""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import fakeredis
from fastapi.testclient import TestClient

from citymate.app import create_app
from citymate.config import Settings
from citymate.knowledge import Knowledge, COLLECTION_NAME, SPLITTER_VERSION
from citymate.runtime import build
from citymate.models import Base


RETRIEVAL_CASES = [
    ("预约草稿多久失效？", "预约规则", "15 分钟"),
    ("填好了预订但还没提交，可以保留多久？", "预约规则", "15 分钟"),
    ("签到能得多少积分？", "社区与积分", "10 积分"),
    ("我今天已经打过卡，再打卡还能加分吗？", "社区与积分", "重复签到不重复增加积分"),
    ("抢到券显示处理中，是已经成功了吗？", "优惠与订单", "受理不等于订单成功"),
    ("平台会真的扣钱退款吗？", "优惠与订单", "不执行真实扣款或退款"),
]
CHAT_CASES = [
    {
        "question": "请检索平台政策，预约草稿的有效期是多久？",
        "source": "预约规则",
        "markers": ["15", "十五"],
    },
    {
        "question": "请检索平台政策，每天签到能得多少积分？重复签到会再次增加吗？",
        "source": "社区与积分",
        "markers": ["10", "十"],
    },
    {
        "question": "请检索平台优惠政策，这个平台会真的扣款和退款吗？",
        "source": "优惠与订单",
        "markers": ["不", "未"],
    },
]


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def main(args):
    if args.output.exists():
        raise SystemExit("Report exists; choose a new output path.")
    config = Settings()
    if args.live and not config.api_key:
        raise SystemExit("No model key configured.")
    workspace = args.output.resolve().parent / (args.output.stem + "-data")
    workspace.mkdir(parents=True, exist_ok=False)
    os.environ["CITYMATE_KNOWLEDGE_MODE"] = "chroma"
    os.environ["CITYMATE_KNOWLEDGE_TRANSPORT"] = "mcp"
    os.environ["CITYMATE_CHROMA_PATH"] = str(workspace / "vectors")
    # Provider error payloads must never be written into evaluation evidence.
    logging.disable(logging.CRITICAL)
    report = {
        "started_at": timestamp(),
        "model": config.model,
        "live_requested": args.live,
        "environment": "Real Chroma default ONNX embeddings + real MCP stdio subprocess + isolated SQLite/FakeRedis + FastAPI TestClient",
        "versions": {
            n: importlib.metadata.version(n)
            for n in ("chromadb", "mcp", "onnxruntime", "openai", "numpy", "posthog")
        },
        "python": sys.version.split()[0],
        "source_sha256": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                Path("citymate/knowledge.py"),
                Path("citymate/knowledge_client.py"),
                Path("citymate/knowledge_server.py"),
                Path("citymate/assistant.py"),
                Path("citymate/app.py"),
                *sorted(Path("citymate/policies").glob("*.txt")),
            ]
        },
        "phases": {},
        "chat_records": [],
        "limits": "Three demo policy documents; keyword checks are not full semantic grading; no browser, production database, remote MCP, load or HA test.",
    }

    def save():
        encoded = json.dumps(report, ensure_ascii=False, indent=2)
        if config.api_key and config.api_key in encoded:
            raise RuntimeError("Refusing to persist a credential")
        args.output.write_text(encoded + "\n", encoding="utf-8")

    try:
        kb = Knowledge()
        stored = kb.collection.get(include=["embeddings", "metadatas"])
        chunk_count = len(kb.chunks)
        assert chunk_count > len(kb.docs)
        assert kb.collection.count() == chunk_count
        assert all(len(v) == 384 for v in stored["embeddings"])
        assert Knowledge().collection.count() == chunk_count
        report["phases"]["chroma"] = {
            "passed": True,
            "documents": len(kb.docs),
            "chunks": chunk_count,
            "collection": COLLECTION_NAME,
            "splitter": SPLITTER_VERSION,
            "chunk_size_chars": kb.chunk_size,
            "chunk_overlap_chars": kb.chunk_overlap,
            "dimensions": 384,
            "embedding": "Chroma default all-MiniLM-L6-v2 ONNX",
            "reopen_count": chunk_count,
        }
        save()
        print("Chroma embedding/persistence PASS", flush=True)

        async def probe():
            from citymate.knowledge_client import connect_knowledge

            async with connect_knowledge() as client:
                assert await client.doc_count_async() == chunk_count
                ranks = []
                for query, title, evidence in RETRIEVAL_CASES:
                    result = await client.search_handler({"query": query, "top_k": 3})
                    assert len(result) == 3
                    assert all(d in kb.chunks for d in result)
                    ranks.append(
                        {
                            "query": query,
                            "expected_title": title,
                            "expected_evidence": evidence,
                            "ranked_titles": [d["title"] for d in result],
                            "ranked_chunks": [
                                {k: d[k] for k in ("chunk_id", "source", "section", "content")}
                                for d in result
                            ],
                            "top1_correct": result[0]["title"] == title,
                            "top1_chunk_correct": (
                                result[0]["title"] == title and evidence in result[0]["content"]
                            ),
                            "top3_chunk_hit": any(
                                d["title"] == title and evidence in d["content"] for d in result
                            ),
                        }
                    )
                return {
                    "passed": True,
                    "tools": sorted(client.tools),
                    "documents": len(kb.docs),
                    "chunks": chunk_count,
                    "retrieval_cases": ranks,
                    "top1_hits": sum(r["top1_correct"] for r in ranks),
                    "top1_chunk_hits": sum(r["top1_chunk_correct"] for r in ranks),
                    "top3_chunk_hits": sum(r["top3_chunk_hit"] for r in ranks),
                    "total_queries": len(ranks),
                }

        report["phases"]["mcp"] = asyncio.run(probe())
        save()
        print("MCP discovery/real-vector-search PASS", flush=True)
        if args.live:
            cfg = Settings(
                database_url="sqlite:///" + str(workspace / "business.sqlite3"),
                redis_url="redis://unused-test-only",
                demo=True,
                uploads=workspace / "uploads",
                api_key=config.api_key,
                model=config.model,
                base_url=config.base_url,
            )
            p, engine = build(cfg, fakeredis.FakeRedis(decode_responses=True))
            try:
                Base.metadata.create_all(engine)
                p.seed()
                with TestClient(
                    create_app(cfg, platform=p), headers={"X-CityMate-Request": "1"}
                ) as http:
                    from citymate.knowledge_client import KnowledgeMCPClient

                    assert isinstance(http.app.state.assistant.kb, KnowledgeMCPClient)
                    code = http.post("/auth/code", json={"phone": "13800009999"})
                    assert code.status_code == 200
                    login = http.post(
                        "/auth/login",
                        json={"phone": "13800009999", "code": code.json()["demo_code"]},
                    )
                    assert login.status_code == 200
                    for case in CHAT_CASES:
                        record = {"question": case["question"], "expected_source": case["source"]}
                        try:
                            response = http.post("/chat", json={"message": case["question"]})
                            record["http_status"] = response.status_code
                            data = response.json()
                            record["result"] = data
                            record["checks"] = {
                                "http_ok": response.status_code == 200,
                                "real_model": data.get("model_calls", 0) > 0,
                                "tool_called": any(
                                    t["tool"] == "knowledge_search"
                                    and isinstance(t["result"], list)
                                    for t in data.get("tools", [])
                                ),
                                "expected_source": any(
                                    s.get("source") == "citymate/" + case["source"] + ".txt"
                                    for s in data.get("sources", [])
                                ),
                                "answer_marker": any(
                                    m in data.get("response", "") for m in case["markers"]
                                ),
                            }
                            record["passed"] = all(record["checks"].values())
                        except Exception as exc:
                            record.update(passed=False, exception_type=type(exc).__name__)
                        report["chat_records"].append(record)
                        save()
                        print(
                            "Live HTTP chat",
                            case["source"],
                            "PASS" if record["passed"] else "FAIL",
                            flush=True,
                        )
                report["phases"]["live_http"] = {
                    "passed": all(r["passed"] for r in report["chat_records"]),
                    "passed_cases": sum(r["passed"] for r in report["chat_records"]),
                    "total_cases": len(report["chat_records"]),
                }
            finally:
                engine.dispose()
                p.r.close()
        report["passed"] = all(p["passed"] for p in report["phases"].values())
    except Exception as exc:
        report.update(passed=False, exception_type=type(exc).__name__)
    finally:
        report["finished_at"] = timestamp()
        save()
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "phases": list(report["phases"]),
                "exception_type": report.get("exception_type"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(main(parser.parse_args()))
