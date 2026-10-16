"""Real MCP transport fixture, deterministic backend; never used in production."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from integrations.knowledge_server import create_server


class Backend:
    def __init__(self):
        self.docs = [{"title": "demo", "content": "转班申请需要审核", "score": 1.0}]

    async def search_async(self, query, top_k):
        if query == "error":
            raise ValueError("fixture failure")
        if query == "slow":
            await asyncio.sleep(2)
        return self.docs[:top_k]

    async def doc_count_async(self):
        return len(self.docs)

    async def add_documents_async(self, documents):
        self.docs.extend(documents)
        return len(documents)


if __name__ == "__main__":
    create_server(Backend()).run(transport="stdio")
