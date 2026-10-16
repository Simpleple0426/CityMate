import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock

from mcp import StdioServerParameters
from mcp.shared.exceptions import McpError
from integrations.knowledge_client import connect_knowledge
from integrations.knowledge_backend import open_knowledge_backend


class KnowledgeMCPTests(unittest.IsolatedAsyncioTestCase):
    def params(self):
        return StdioServerParameters(command=sys.executable,
            args=[str(Path(__file__).parent / "fixtures" / "knowledge_stdio.py")])

    async def test_discovery_search_import_and_parallel_calls(self):
        async with connect_knowledge(self.params()) as backend:
            self.assertIn("query", backend.tools["knowledge_search"].inputSchema["properties"])
            self.assertEqual(await backend.doc_count_async(), 1)
            rows = await backend.search_handler({"query": "转班", "top_k": 1})
            self.assertIn("审核", rows[0]["content"])
            self.assertEqual(await backend.add_documents_async([{"content": "新资料"}]), 1)
            self.assertEqual(await backend.doc_count_async(), 2)
            results = await asyncio.gather(*(backend.search_handler({"query": "政策"}) for _ in range(3)))
            self.assertTrue(all(len(rows) == 2 for rows in results))

    async def test_tool_errors_and_schema_validation_do_not_kill_session(self):
        async with connect_knowledge(self.params()) as backend:
            for args in ({"query": "error"}, {"query": "ok", "top_k": 0}):
                with self.assertRaises(RuntimeError):
                    await backend.search_handler(args)
            self.assertEqual(await backend.doc_count_async(), 1)

    async def test_timeout_closes_transport(self):
        async with connect_knowledge(self.params(), timeout_s=0.5) as backend:
            with self.assertRaises(McpError):
                await backend.search_handler({"query": "slow"})
        # A fresh process/session remains usable after timed-out context cleanup.
        async with connect_knowledge(self.params()) as backend:
            self.assertEqual(await backend.doc_count_async(), 1)

    async def test_invalid_transport_rejected(self):
        with patch.dict(os.environ, {"COURSEPILOT_KNOWLEDGE_TRANSPORT": "typo"}):
            with self.assertRaises(ValueError):
                async with open_knowledge_backend():
                    pass

    async def test_agent_rag_adapter_uses_mcp_and_manager_fallback(self):
        from agents.tools import build_shared_rag_tools
        from agents.agent_orchestrator import Request
        from integrations.tool_manager import MCPToolManager, Tool
        manager = MCPToolManager(api_key="test-only")
        try:
            async with connect_knowledge(self.params()) as backend:
                manager.register(Tool(name="knowledge_search", description="test",
                    handler=backend.search_handler,
                    schema=backend.tools["knowledge_search"].inputSchema, cache_ttl=300,
                    fallback=lambda *_: [{"content": "unavailable", "fallback": True}]))
                manager.rewrite_query = AsyncMock(return_value=["政策"])
                manager._rerank = AsyncMock(side_effect=lambda query, rows, k: rows[:k])
                tool = build_shared_rag_tools(manager)["search_knowledge_base"]
                result = await tool.handler(Request("政策", "u", "c"), {"query": "政策"})
                self.assertTrue(result["success"])
                self.assertIn("审核", result["results"][0]["content"])
                self.assertTrue(manager._cache)
                manager.clear_cache()
                self.assertFalse(manager._cache)
                failed = await manager.call("knowledge_search", {"query": "error"})
                self.assertTrue(failed.data[0]["fallback"])
        finally:
            await manager._client.close()

    async def test_existing_http_import_and_stats_use_mcp_backend(self):
        import httpx
        from types import SimpleNamespace
        from unittest.mock import Mock
        import api.main as api
        cache = SimpleNamespace(clear_cache=Mock())
        async with connect_knowledge(self.params()) as backend:
            with patch.object(api, "_knowledge_backend", backend), patch.object(api, "_tool_manager", cache):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
                    response = await client.post("/knowledge/add", json={"documents": [{"title": "test", "content": "测试资料"}]})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["added_chunks"], 1)
                    response = await client.post("/knowledge/upload", files={"file": ("policy.txt", "上传资料".encode("utf-8"), "text/plain")})
                    self.assertEqual(response.status_code, 200)
                    response = await client.get("/knowledge/stats")
                    self.assertEqual(response.json()["total_chunks"], 3)
                    self.assertEqual(cache.clear_cache.call_count, 2)


if __name__ == "__main__":
    unittest.main()
