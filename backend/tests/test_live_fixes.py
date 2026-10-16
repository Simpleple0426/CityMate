import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.intent_recognizer import IntentRecognizer, _TEMPLATES
from memory.conversation_memory import MemoryManager


class LiveFixTests(unittest.IsolatedAsyncioTestCase):
    async def test_template_embeddings_are_batched_and_cached(self):
        recognizer = IntentRecognizer.__new__(IntentRecognizer)
        recognizer._tpl_embeddings = {}
        async def embed(**kwargs):
            return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[float(i), 1.0])
                                         for i, _ in enumerate(kwargs['input'])])
        create = AsyncMock(side_effect=embed)
        recognizer.client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
        await recognizer._load_template_embeddings()
        await recognizer._load_template_embeddings()
        self.assertEqual(create.await_count, 1)
        self.assertEqual(sum(map(len, recognizer._tpl_embeddings.values())), sum(map(len, _TEMPLATES.values())))

    async def test_failed_template_batch_keeps_query_in_same_vector_space(self):
        recognizer = IntentRecognizer.__new__(IntentRecognizer)
        recognizer._tpl_embeddings = {}
        create = AsyncMock(side_effect=RuntimeError('unavailable'))
        recognizer.client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
        await recognizer._load_template_embeddings()
        query = await recognizer._embed_text('转班')
        self.assertEqual(create.await_count, 1)
        self.assertEqual(len(query), len(next(iter(recognizer._tpl_embeddings.values()))[0]))

    async def test_memory_filter_is_accepted_by_real_chroma_validator(self):
        from chromadb.api.types import validate_where
        manager = MemoryManager.__new__(MemoryManager)
        async def query(*args, **kwargs):
            validate_where(kwargs['where'])
            return {'documents': [['已核验历史']]}
        manager._query_episodic = AsyncMock(side_effect=query)
        result = await manager._search_episodic('u', 'c', '转班')
        self.assertEqual(result, ['已核验历史'])
