"""Tests for rag.fts_index.FtsIndex."""

from pathlib import Path

import pytest

from rag.fts_index import FtsIndex


@pytest.fixture
def fts(tmp_path: Path) -> FtsIndex:
    return FtsIndex(str(tmp_path / "fts.db"))


def test_upsert_and_search_returns_match(fts: FtsIndex):
    fts.upsert("a.md", "AI Overview", "科技/AI/模型", "this doc explains llm and gpt")
    hits = fts.search("llm")
    assert len(hits) == 1
    assert hits[0]["path"] == "a.md"
    assert "llm" in hits[0]["snippet"]


def test_upsert_is_idempotent_on_path(fts: FtsIndex):
    fts.upsert("a.md", "T1", "c1", "alpha beta")
    fts.upsert("a.md", "T2", "c2", "gamma delta")
    assert fts.count() == 1
    # Latest content wins.
    hits = fts.search("gamma")
    assert len(hits) == 1
    assert hits[0]["title"] == "T2"
    assert hits[0]["category"] == "c2"


def test_delete_removes_by_path(fts: FtsIndex):
    fts.upsert("a.md", "T", "c", "alpha")
    fts.upsert("b.md", "T", "c", "beta")
    assert fts.count() == 2
    n = fts.delete("a.md")
    assert n == 1
    assert fts.count() == 1
    assert fts.search("alpha") == []


def test_search_returns_empty_for_blank_query(fts: FtsIndex):
    fts.upsert("a.md", "T", "c", "alpha")
    assert fts.search("") == []
    assert fts.search("   ") == []


def test_search_supports_chinese_trigram(tmp_path: Path):
    fts = FtsIndex(str(tmp_path / "fts.db"))
    fts.upsert("zh.md", "AI 研发", "科技/AI/研发体系", "本文讨论大语言模型与研发流程")
    # trigram tokenizer requires >= 3 chars for MATCH; use a 4-char phrase.
    hits = fts.search("大语言模")
    assert len(hits) >= 1
    assert hits[0]["path"] == "zh.md"
    fts.close()


def test_search_short_chinese_falls_back_to_like(tmp_path: Path):
    fts = FtsIndex(str(tmp_path / "fts.db"))
    fts.upsert("zh.md", "AI 研发", "科技/AI/研发体系", "本文讨论简历怎么写")
    # 2-char query triggers LIKE fallback path.
    hits = fts.search("简历")
    assert len(hits) == 1
    assert hits[0]["path"] == "zh.md"
    fts.close()


def test_search_rank_orders_by_relevance(fts: FtsIndex):
    fts.upsert("a.md", "T", "c", "alpha alpha alpha llm")
    fts.upsert("b.md", "T", "c", "llm")
    fts.upsert("c.md", "T", "c", "alpha")
    hits = fts.search("alpha llm")
    paths = [h["path"] for h in hits]
    assert paths[0] == "a.md"  # most alpha occurrences


def test_search_limit_truncates(fts: FtsIndex):
    for i in range(20):
        fts.upsert(f"f{i}.md", "T", "c", "alpha keyword")
    hits = fts.search("alpha", limit=5)
    assert len(hits) == 5


def test_close_does_not_raise(fts: FtsIndex):
    fts.close()
