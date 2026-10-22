"""Opt-in real Chroma embeddings and MCP subprocess tests; no live LLM calls."""

import asyncio
import os

import pytest
from fastapi.testclient import TestClient

from citymate.app import create_app
from citymate.knowledge import Knowledge
from .conftest import login
from .test_agent import ScriptedModel, answer, calls

pytestmark = pytest.mark.skipif(
    os.getenv("CITYMATE_TEST_KNOWLEDGE") != "true",
    reason="Set CITYMATE_TEST_KNOWLEDGE=true after installing requirements-ai.txt",
)


def test_chroma_real_embeddings_persist_without_duplicate_documents(monkeypatch, tmp_path):
    monkeypatch.setenv("CITYMATE_KNOWLEDGE_MODE", "chroma")
    monkeypatch.setenv("CITYMATE_CHROMA_PATH", str(tmp_path / "vectors"))
    kb = Knowledge()
    assert len(kb.chunks) > len(kb.docs)
    assert kb.collection is not None and kb.collection.count() == len(kb.chunks)
    stored = kb.collection.get(include=["embeddings", "documents", "metadatas"])
    assert len(stored["embeddings"]) == len(kb.chunks)
    assert all(len(vector) == 384 for vector in stored["embeddings"])
    assert {m["source"] for m in stored["metadatas"]} == {d["source"] for d in kb.docs}
    assert {m["chunk_id"] for m in stored["metadatas"]} == set(stored["ids"])
    reopened = Knowledge()
    assert reopened.collection.count() == len(kb.chunks)
    result = asyncio.run(reopened.search_async("预约草稿多久过期", top_k=1))
    assert len(result) == 1 and result[0] in kb.chunks


def test_chroma_replaces_updated_deleted_and_empty_policy_chunks(monkeypatch, tmp_path):
    monkeypatch.setenv("CITYMATE_KNOWLEDGE_MODE", "chroma")
    monkeypatch.setenv("CITYMATE_CHROMA_PATH", str(tmp_path / "vectors"))
    policies = tmp_path / "policies"
    policies.mkdir()
    first, second = policies / "预约.txt", policies / "积分.txt"
    first.write_text("# 预约\n\n草稿有效15分钟。\n\n需确认后审核。", encoding="utf-8")
    second.write_text("签到可得10积分。", encoding="utf-8")
    old = Knowledge(policies)
    old_ids = set(old.collection.get(include=[])["ids"])
    first.write_text("# 预约\n\n测试更新规则：草稿有效20分钟。", encoding="utf-8")
    second.unlink()
    new = Knowledge(policies)
    stored = new.collection.get(include=["documents", "metadatas"])
    assert len(stored["ids"]) == 1 and not old_ids & set(stored["ids"])
    assert "20分钟" in stored["documents"][0]
    assert stored["metadatas"][0]["document_version"] == new.chunks[0]["document_version"]
    first.write_text("", encoding="utf-8")
    empty = Knowledge(policies)
    assert empty.collection.count() == 0
    assert asyncio.run(empty.search_async("预约")) == []


@pytest.mark.parametrize("mode", ["lexical", "chroma"])
def test_real_mcp_discovery_search_validation_and_read_only(monkeypatch, tmp_path, mode):
    from citymate.knowledge_client import connect_knowledge

    monkeypatch.setenv("CITYMATE_KNOWLEDGE_MODE", mode)
    monkeypatch.setenv("CITYMATE_CHROMA_PATH", str(tmp_path / "vectors"))
    monkeypatch.setenv("CITYMATE_KNOWLEDGE_CHUNK_SIZE", "32")
    monkeypatch.setenv("CITYMATE_KNOWLEDGE_CHUNK_OVERLAP", "6")
    expected_count = len(Knowledge().chunks)

    async def scenario():
        async with connect_knowledge() as kb:
            assert set(kb.tools) == {"knowledge_search", "knowledge_stats", "knowledge_add"}
            assert await kb.doc_count_async() == expected_count
            result = await kb.search_handler({"query": "签到可得 10 积分", "top_k": 3})
            assert len(result) == 3
            assert any("10 积分" in d["content"] for d in result)
            assert all(d["chunk_id"] and d["section"] and d["document_version"] for d in result)
            with pytest.raises(RuntimeError, match="MCP tool failed"):
                await kb.search_handler({"query": "预约", "top_k": 0})
            with pytest.raises(RuntimeError, match="MCP tool failed"):
                await kb.add_documents_async([{"content": "未经审核的新规则"}])
            assert await kb.doc_count_async() == expected_count
        # A closed transport cannot silently return fabricated search results.
        with pytest.raises(Exception):
            await kb.search_handler({"query": "预约"})

    asyncio.run(scenario())


@pytest.mark.parametrize("transport", ["local", "mcp"])
@pytest.mark.parametrize("mode", ["lexical", "chroma"])
def test_http_chat_uses_real_retrieval_backend(platform, monkeypatch, tmp_path, transport, mode):
    monkeypatch.setenv("CITYMATE_KNOWLEDGE_MODE", mode)
    monkeypatch.setenv("CITYMATE_KNOWLEDGE_TRANSPORT", transport)
    monkeypatch.setenv("CITYMATE_CHROMA_PATH", str(tmp_path / "vectors"))
    monkeypatch.setenv("CITYMATE_KNOWLEDGE_CHUNK_SIZE", "48")
    monkeypatch.setenv("CITYMATE_KNOWLEDGE_CHUNK_OVERLAP", "8")
    expected_count = len(Knowledge().chunks)
    with TestClient(
        create_app(platform.cfg, platform=platform), headers={"X-CityMate-Request": "1"}
    ) as client:
        assistant = client.app.state.assistant
        assert client.portal.call(assistant.kb.doc_count_async) == expected_count
        if transport == "mcp":
            from citymate.knowledge_client import KnowledgeMCPClient

            assert isinstance(assistant.kb, KnowledgeMCPClient)
        else:
            assert (assistant.kb.collection is not None) == (mode == "chroma")
        assistant.client = ScriptedModel(
            calls(("knowledge_search", {"query": "预约先生成有效期 15 分钟的草稿"})),
            answer("根据检索到的预约规则，草稿有效期为15分钟。"),
        )
        response = client.post("/chat", headers=login(client), json={"message": "预约草稿多久有效"})
        assert response.status_code == 200
        result = response.json()
        assert result["tools"][0]["tool"] == "knowledge_search"
        assert any(
            s["source"] == "citymate/预约规则.txt" and "15 分钟" in s["content"]
            for s in result["sources"]
        )
        assert result["model_calls"] == 2  # Scripted model; retrieval and MCP are real.
        tool_result = assistant.client.requests[1]["messages"][-1]["content"]
        assert "chunk_id" in tool_result and "start_char" in tool_result
