"""MCP client for the application policy service."""

import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class KnowledgeMCPClient:
    def __init__(self, session, tools, timeout_s=20):
        self.session = session
        self.timeout = timedelta(seconds=timeout_s)
        self.tools = {tool.name: tool for tool in tools}
        if not {"knowledge_search", "knowledge_stats", "knowledge_add"} <= self.tools.keys():
            raise RuntimeError("MCP knowledge service is missing required tools")

    async def _call(self, name, arguments):
        result = await self.session.call_tool(name, arguments, read_timeout_seconds=self.timeout)
        if result.isError:
            raise RuntimeError(f"MCP tool failed: {name}")
        text = [block.text for block in result.content if block.type == "text"]
        if len(text) != 1:
            raise ValueError(f"Unexpected MCP response: {name}")
        return json.loads(text[0])

    async def search_handler(self, params, context=None):
        result = await self._call("knowledge_search", params)
        if not isinstance(result, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("content"), str)
            for item in result
        ):
            raise ValueError("Invalid MCP search result")
        return result

    async def add_documents_async(self, documents):
        return (await self._call("knowledge_add", {"documents": documents}))["added_chunks"]

    async def doc_count_async(self):
        return (await self._call("knowledge_stats", {}))["total_chunks"]


@asynccontextmanager
async def connect_knowledge(parameters=None, timeout_s=20):
    if parameters is None:
        # Forward only runtime/Chroma settings; the search service does not need LLM secrets.
        env = {
            key: value
            for key, value in os.environ.items()
            if key.startswith("CITYMATE_KNOWLEDGE_")
            or key == "CITYMATE_CHROMA_PATH"
            or key
            in {
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "PATH",
                "HOME",
                "USERPROFILE",
                "LOCALAPPDATA",
            }
        }
        env["PYTHONIOENCODING"] = "utf-8"
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "citymate.knowledge_server"],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=env,
        )
    # Enter and exit both contexts in the same lifespan task (AnyIO cancel scope ownership).
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(
            read, write, read_timeout_seconds=timedelta(seconds=20)
        ) as session:
            await session.initialize()
            discovered = await session.list_tools()
            yield KnowledgeMCPClient(session, discovered.tools, timeout_s)
