"""Chunk coverage, provenance and retrieval checks without external models."""

import asyncio

import pytest

from citymate.knowledge import Knowledge, split_document


def document(text):
    return {"title": "预约规则", "source": "citymate/预约规则.txt", "content": text}


def test_sections_paragraphs_and_exact_source_offsets():
    text = "# 预约政策\n\n## 草稿\n  草稿有效期15分钟。\n确认后待审核。\n\n另一段补充说明。\n\n## 审核\n批准后才占名额。\n"
    chunks = split_document(document(text))
    assert len(chunks) == 3
    assert [c["section"] for c in chunks] == ["预约政策 / 草稿"] * 2 + ["预约政策 / 审核"]
    assert chunks[0]["content"] == "草稿有效期15分钟。\n确认后待审核。"
    assert chunks[2]["content"] == "批准后才占名额。"
    for chunk in chunks:
        assert chunk["content"] == text[chunk["start_char"] : chunk["end_char"]]
        assert chunk["source"] == "citymate/预约规则.txt"


@pytest.mark.parametrize("size,overlap", [(80, 16), (80, 0), (2, 1)])
def test_long_unicode_paragraph_has_bounded_chunks_without_lost_text(size, overlap):
    text = ("预约确认后仍需管理员审核🙂。" * 50) + "最后一个条件不能丢失。"
    chunks = split_document(document(text), size, overlap)
    assert len(chunks) > 1
    covered = set()
    for chunk in chunks:
        assert 0 < len(chunk["content"]) <= size
        assert text[chunk["start_char"] : chunk["end_char"]] == chunk["content"]
        covered.update(range(chunk["start_char"], chunk["end_char"]))
    assert covered == set(range(len(text)))
    for previous, current in zip(chunks, chunks[1:]):
        assert previous["end_char"] - current["start_char"] == overlap
        assert current["start_char"] > previous["start_char"]


def test_chunk_ids_are_repeatable_and_versioned():
    original = split_document(document("# 政策\n\n预约需确认。\n\n审核后生效。"))
    assert original == split_document(document("# 政策\n\n预约需确认。\n\n审核后生效。"))
    updated = split_document(document("# 政策\n\n预约需确认。\n\n审核后生效。内容已更新。"))
    assert original[0]["document_id"] == updated[0]["document_id"]
    assert original[0]["document_version"] != updated[0]["document_version"]
    assert not {c["chunk_id"] for c in original} & {c["chunk_id"] for c in updated}
    assert [c["chunk_index"] for c in original] == [0, 1]


@pytest.mark.parametrize("size,overlap", [(0, 0), (20, -1), (20, 20), (20, 21)])
def test_invalid_chunk_settings_are_rejected(size, overlap):
    with pytest.raises(ValueError):
        split_document(document("正文"), size, overlap)


def test_chunk_retrieval_returns_only_relevant_paragraph_with_source(monkeypatch, tmp_path):
    monkeypatch.setenv("CITYMATE_KNOWLEDGE_MODE", "lexical")
    source = "# 政策\n\n## 预约\n预约草稿15分钟失效。\n\n## 社区\n签到获得10积分。"
    (tmp_path / "政策.txt").write_text(source, encoding="utf-8")
    kb = Knowledge(tmp_path)
    assert len(kb.docs) == 1 and asyncio.run(kb.doc_count_async()) == 2
    result = asyncio.run(kb.search_async("预约草稿", top_k=1))
    assert result[0]["content"] == "预约草稿15分钟失效。"
    assert result[0]["section"] == "政策 / 预约"
    assert result[0]["source"] == "citymate/政策.txt"
    assert "签到" not in result[0]["content"]


def test_empty_corpus_and_search_argument_validation(monkeypatch, tmp_path):
    monkeypatch.setenv("CITYMATE_KNOWLEDGE_MODE", "lexical")
    (tmp_path / "empty.txt").write_text("# 暂无政策\n\n", encoding="utf-8")
    kb = Knowledge(tmp_path)
    assert kb.chunks == []
    assert asyncio.run(kb.search_async("预约")) == []
    for query, top_k in [(" ", 1), ("预约", 0), ("预约", 11), ("预约", True)]:
        with pytest.raises(ValueError):
            asyncio.run(kb.search_async(query, top_k))
