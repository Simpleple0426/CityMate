"""Explicit transport selection; MCP failures never silently switch to direct calls."""
import os
from contextlib import asynccontextmanager


@asynccontextmanager
async def open_knowledge_backend():
    mode = os.getenv("COURSEPILOT_KNOWLEDGE_TRANSPORT", "mcp").lower()
    if mode == "mcp":
        from integrations.knowledge_client import connect_knowledge
        async with connect_knowledge() as backend:
            yield backend
    elif mode == "local":
        from integrations.knowledge_base import KnowledgeBase
        yield KnowledgeBase(
            chroma_host=os.getenv("CHROMA_HOST", "chromadb"),
            chroma_port=int(os.getenv("CHROMA_PORT", "8000")),
            chroma_path=os.getenv("CHROMA_PERSIST_DIRECTORY", "./data/chroma"),
        )
    else:
        raise ValueError("COURSEPILOT_KNOWLEDGE_TRANSPORT must be mcp or local")
