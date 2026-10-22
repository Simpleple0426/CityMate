"""Section/paragraph policy chunks shared by lexical, Chroma and MCP retrieval."""

import asyncio
import hashlib
import os
import re
from pathlib import Path


COLLECTION_NAME = "citymate_policy_chunks_v1"
SPLITTER_VERSION = "paragraph-char-v1"


def split_document(document, chunk_size=320, chunk_overlap=48):
    """Keep paragraphs/heading boundaries; overlap only within oversized paragraphs.

    Sizes and offsets are Python Unicode characters, not model tokens. Offsets
    address the newline-normalized source text loaded by Path.read_text().
    """
    if chunk_size < 2 or not 0 <= chunk_overlap < chunk_size:
        raise ValueError("Require chunk_size >= 2 and 0 <= chunk_overlap < chunk_size")
    text = document["content"]
    version = hashlib.sha256(text.encode("utf-8")).hexdigest()
    document_id = hashlib.sha256(document["source"].encode("utf-8")).hexdigest()
    paragraphs, headings = [], []
    start, end, offset = None, 0, 0
    section = document["title"]
    for line in text.splitlines(keepends=True):
        heading = re.match(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if not line.strip() or heading:
            if start is not None:
                paragraphs.append((start, end, section))
                start = None
            if heading:
                level, title = len(heading[1]), heading[2]
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, title))
                section = " / ".join(title for _, title in headings)
        else:
            if start is None:
                start = offset + len(line) - len(line.lstrip())
            end = offset + len(line.rstrip())
        offset += len(line)
    if start is not None:
        paragraphs.append((start, end, section))

    chunks = []
    for start, end, section in paragraphs:
        while start < end:
            stop = min(start + chunk_size, end)
            if stop < end:
                # Prefer a sentence/word boundary in the latter half of the window.
                lower = start + max(chunk_size // 2, chunk_overlap + 1)
                boundaries = list(re.finditer(r"[。！？；.!?;]\s*|\s+", text[lower:stop]))
                if boundaries:
                    stop = lower + boundaries[-1].end()
            raw = text[start:stop]
            left = start + len(raw) - len(raw.lstrip())
            right = stop - (len(raw) - len(raw.rstrip()))
            if left < right:
                identity = f"{document_id}:{version}:{SPLITTER_VERSION}:{section}:{left}:{right}"
                chunks.append(
                    {
                        "content": text[left:right],
                        "title": document["title"],
                        "source": document["source"],
                        "document_id": document_id,
                        "document_version": version,
                        "section": section,
                        "chunk_index": len(chunks),
                        "start_char": left,
                        "end_char": right,
                        "chunk_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                    }
                )
            if stop == end:
                break
            start = stop - chunk_overlap
    return chunks


class Knowledge:
    def __init__(self, policy_dir=None):
        policy_dir = (
            Path(policy_dir) if policy_dir is not None else Path(__file__).parent / "policies"
        )
        self.chunk_size = int(os.getenv("CITYMATE_KNOWLEDGE_CHUNK_SIZE", "320"))
        self.chunk_overlap = int(os.getenv("CITYMATE_KNOWLEDGE_CHUNK_OVERLAP", "48"))
        if self.chunk_size < 2 or not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("Invalid policy chunk size/overlap")
        self.docs = [
            {
                "title": p.stem,
                "content": p.read_text(encoding="utf-8-sig"),
                "source": "citymate/" + p.name,
            }
            for p in sorted(policy_dir.glob("*.txt"))
        ]
        self.chunks = [
            chunk
            for document in self.docs
            for chunk in split_document(document, self.chunk_size, self.chunk_overlap)
        ]
        self.collection = None
        if os.getenv("CITYMATE_KNOWLEDGE_MODE", "lexical") == "chroma":
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            client = chromadb.PersistentClient(
                path=os.getenv("CITYMATE_CHROMA_PATH", "./data/citymate/chroma"),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            # Dedicated chunk collection; the old document-level index is left intact.
            self.collection = client.get_or_create_collection(COLLECTION_NAME)
            wanted = {chunk["chunk_id"] for chunk in self.chunks}
            existing = set(self.collection.get(include=[])["ids"])
            for offset in range(0, len(self.chunks), 200):
                batch = self.chunks[offset : offset + 200]
                self.collection.upsert(
                    ids=[d["chunk_id"] for d in batch],
                    documents=[d["content"] for d in batch],
                    metadatas=[{k: v for k, v in d.items() if k != "content"} for d in batch],
                )
            # Source files are authoritative: edits/deletions must not leave stale policy hits.
            obsolete = sorted(existing - wanted)
            for offset in range(0, len(obsolete), 200):
                self.collection.delete(ids=obsolete[offset : offset + 200])

    async def search_async(self, query, top_k=5):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 4000:
            raise ValueError("Invalid search query")
        if type(top_k) is not int or not 1 <= top_k <= 10:
            raise ValueError("top_k must be an integer between 1 and 10")
        if not self.chunks:
            return []
        if self.collection is not None:
            result = await asyncio.to_thread(
                self.collection.query, query_texts=[query], n_results=min(top_k, len(self.chunks))
            )
            return [
                {"content": doc, **meta}
                for doc, meta in zip(result["documents"][0], result["metadatas"][0])
            ]
        # Explicit lightweight fallback, not described as semantic retrieval.
        terms = {query[i : i + 2] for i in range(max(1, len(query) - 1))}
        ranked = sorted(
            self.chunks,
            key=lambda d: sum(t in d["content"] + d["section"] + d["title"] for t in terms),
            reverse=True,
        )
        return ranked[:top_k]

    async def search_handler(self, params, context=None):
        return await self.search_async(params["query"], params.get("top_k", 5))

    async def doc_count_async(self):
        # Kept for the existing MCP client API; knowledge_stats exposes total_chunks.
        return len(self.chunks)

    async def add_documents_async(self, documents):
        raise ValueError("CityMate policies are versioned files; edit files and restart to publish")
