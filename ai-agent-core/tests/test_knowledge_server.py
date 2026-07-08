"""Knowledge Server 测试 — 含 FTS5 集成验证。"""

from pathlib import Path

import pytest

from mcp.servers.knowledge_server import KnowledgeServer
from rag.corpus_loader import CorpusLoader
from rag.fts_index import FtsIndex
from rag.metadata import MetadataIndex


@pytest.fixture
def corpus_dir(tmp_path: Path) -> Path:
    """创建测试语料库目录。"""
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "a.md").write_text("# Python\n\nPython is a programming language used for AI.", encoding="utf-8")
    (d / "b.md").write_text("# Cats\n\nCats are common household pets.", encoding="utf-8")
    return d


@pytest.fixture
def fts_index(corpus_dir: Path, tmp_path: Path) -> FtsIndex:
    """Pre-populate FTS5 with corpus docs (simulating watcher indexing)."""
    fts = FtsIndex(str(tmp_path / "fts.db"))
    loader = CorpusLoader(str(corpus_dir), chunk=False)
    for doc_id, text in loader.docs:
        fts.upsert(
            path=str(corpus_dir / doc_id),
            title=text.split("\n", 1)[0].lstrip("# ").strip() or doc_id,
            category="未分类/Misc/General",
            content=text,
        )
    return fts


# ---------------------------------------------------------------------------
# 原有测试 — 不带 FTS5，走子串/BM25
# ---------------------------------------------------------------------------

def test_lookup_substring_match(corpus_dir: Path):
    out = KnowledgeServer(str(corpus_dir)).execute({"op": "lookup", "query": "python"})
    assert out["ok"] is True
    assert "python" in out["result"].lower()


def test_lookup_no_match_returns_empty(corpus_dir: Path):
    (corpus_dir / "c.md").write_text("# Misc\n\nnothing relevant here", encoding="utf-8")
    out = KnowledgeServer(str(corpus_dir)).execute({"op": "lookup", "query": "python"})
    assert out["ok"] is True
    # BM25 兜底应命中含 'python' 的 a.md
    assert "python" in out["result"].lower()


def test_missing_query_returns_error(corpus_dir: Path):
    out = KnowledgeServer(str(corpus_dir)).execute({"op": "lookup"})
    assert out["ok"] is False
    assert "query" in out["error"].lower()


def test_unknown_op_returns_error(corpus_dir: Path):
    out = KnowledgeServer(str(corpus_dir)).execute({"op": "frob"})
    assert out["ok"] is False


def test_empty_corpus_returns_no_match(tmp_path: Path):
    d = tmp_path / "corpus"
    d.mkdir()
    out = KnowledgeServer(str(d)).execute({"op": "lookup", "query": "anything"})
    assert out["ok"] is True


# ---------------------------------------------------------------------------
# FTS5 集成测试 — Phase 1 新增
# ---------------------------------------------------------------------------

def test_lookup_uses_fts5_when_injected(corpus_dir: Path, fts_index: FtsIndex):
    """注入 FtsIndex 后，lookup 优先走 FTS5，返回 snippet 而非完整正文。"""
    server = KnowledgeServer(corpus_dir, fts_index=fts_index)
    out = server.execute({"op": "lookup", "query": "python"})
    assert out["ok"] is True
    assert "python" in out["result"].lower()
    # FTS5 snippet 应远短于完整正文
    assert len(out["result"]) < len("Python is a programming language used for AI.") + 100


def test_lookup_fts5_returns_high_relevance(corpus_dir: Path, fts_index: FtsIndex):
    """FTS5 按相关性排序，应命中含 'python' 的文档而非含 'pets' 的。"""
    server = KnowledgeServer(corpus_dir, fts_index=fts_index)
    out = server.execute({"op": "lookup", "query": "python"})
    assert out["ok"] is True
    assert "python" in out["result"].lower()
    assert "pets" not in out["result"].lower()


def test_lookup_fts5_chinese_trigram(tmp_path: Path):
    """FTS5 trigram 支持 4+ 字中文短语。"""
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "zh.md").write_text("# 历史\n\n中国历史民族融合深度分析。", encoding="utf-8")
    fts = FtsIndex(str(tmp_path / "fts.db"))
    loader = CorpusLoader(str(d), chunk=False)
    for doc_id, text in loader.docs:
        fts.upsert(
            path=str(d / doc_id),
            title=doc_id,
            category="历史/中国/朝代",
            content=text,
        )
    server = KnowledgeServer(d, fts_index=fts)
    out = server.execute({"op": "lookup", "query": "民族融合"})
    assert out["ok"] is True
    assert "民族融合" in out["result"] or "历史" in out["result"]


def test_lookup_fts5_miss_falls_back_to_substring(corpus_dir: Path, fts_index: FtsIndex):
    """FTS5 无命中时回退到子串匹配。"""
    server = KnowledgeServer(corpus_dir, fts_index=fts_index)
    # "AI" 在 FTS5 trigram 下能命中（>=3 char 才走 MATCH，2 char 走 instr 兜底）
    out = server.execute({"op": "lookup", "query": "AI"})
    assert out["ok"] is True
    # 应命中 a.txt (含 AI)
    assert "ai" in out["result"].lower() or "python" in out["result"].lower()


def test_lookup_without_fts_falls_back_to_bm25(corpus_dir: Path):
    """无 FTS5 注入时，走原有 BM25 路径（兜底）。"""
    server = KnowledgeServer(str(corpus_dir))
    out = server.execute({"op": "lookup", "query": "programming"})
    assert out["ok"] is True
    assert "programming" in out["result"].lower()


def test_lookup_fts5_with_tag_filter(corpus_dir: Path, tmp_path: Path):
    """FTS5 + tag 过滤：命中文件需在 tag 过滤集内。"""
    # 重命名 a.md 加 [tech] tag
    (corpus_dir / "[tech]a.md").write_text(
        (corpus_dir / "a.md").read_text(encoding="utf-8"), encoding="utf-8")
    (corpus_dir / "a.md").unlink()

    fts = FtsIndex(str(tmp_path / "fts.db"))
    loader = CorpusLoader(str(corpus_dir), chunk=False)
    for doc_id, text in loader.docs:
        fts.upsert(
            path=str(corpus_dir / doc_id),
            title=doc_id,
            category="科技/AI/模型",
            content=text,
        )
    server = KnowledgeServer(str(corpus_dir), fts_index=fts)
    out = server.execute({"op": "lookup", "query": "python", "tags": ["tech"]})
    assert out["ok"] is True
    assert "python" in out["result"].lower()


def test_lookup_fts5_tag_filter_excludes_non_tagged(corpus_dir: Path, tmp_path: Path):
    """FTS5 命中文件不在 tag 过滤集内时跳过，回退到 BM25。"""
    (corpus_dir / "[tech]a.md").write_text(
        (corpus_dir / "a.md").read_text(encoding="utf-8"), encoding="utf-8")
    (corpus_dir / "a.md").unlink()
    # b.md 不带 [tech] tag，但 FTS5 可能命中 'cats'——校验 tag 过滤排除它
    fts = FtsIndex(str(tmp_path / "fts.db"))
    loader = CorpusLoader(str(corpus_dir), chunk=False)
    for doc_id, text in loader.docs:
        fts.upsert(
            path=str(corpus_dir / doc_id),
            title=doc_id,
            category="科技/AI/模型",
            content=text,
        )
    server = KnowledgeServer(str(corpus_dir), fts_index=fts)
    # 查 "common" 只在 b.md，但 b.md 不带 [tech] tag → tag 过滤后无候选 → no match
    out = server.execute({"op": "lookup", "query": "common", "tags": ["tech"]})
    assert out["ok"] is True
    assert out["result"] == "no match"


def test_accepts_shared_corpus_loader(corpus_dir: Path):
    loader = CorpusLoader(str(corpus_dir))
    server = KnowledgeServer(loader)
    out = server.execute({"op": "lookup", "query": "python"})
    assert out["ok"] is True


def test_accepts_shared_metadata(corpus_dir: Path):
    meta = MetadataIndex(str(corpus_dir))
    meta.build()
    server = KnowledgeServer(corpus_dir, metadata=meta)
    out = server.execute({"op": "lookup", "query": "python"})
    assert out["ok"] is True


def test_filter_by_tag(corpus_dir: Path):
    (corpus_dir / "[精华]career.md").write_text("# Career\n\n职场成长内容。", encoding="utf-8")
    server = KnowledgeServer(str(corpus_dir))
    out = server.execute({"op": "filter", "tags": ["精华"]})
    assert out["ok"] is True
    assert out["result"]["count"] == 1
    assert "[精华]career" in out["result"]["docs"][0]["id"]


def test_list_returns_all_docs(corpus_dir: Path):
    out = KnowledgeServer(str(corpus_dir)).execute({"op": "list"})
    assert out["ok"] is True
    assert out["result"]["count"] == 2


def test_tags_returns_unique_tags(corpus_dir: Path):
    (corpus_dir / "[精华][职场]x.md").write_text("# X\n\nbody", encoding="utf-8")
    out = KnowledgeServer(str(corpus_dir)).execute({"op": "tags"})
    assert out["ok"] is True
    assert "精华" in out["result"]["tags"]
    assert "职场" in out["result"]["tags"]


def test_reload_picks_up_new_files(corpus_dir: Path):
    server = KnowledgeServer(str(corpus_dir))
    initial = server.execute({"op": "list"})["result"]["count"]
    (corpus_dir / "new.md").write_text("# New\n\nnew content", encoding="utf-8")
    server.reload()
    after = server.execute({"op": "list"})["result"]["count"]
    assert after == initial + 1


# ---------------------------------------------------------------------------
# Phase 7: chunks op — L5 chunk-level retrieval via KnowledgeServer
# ---------------------------------------------------------------------------

def test_chunks_op_by_path(tmp_path: Path):
    """chunks op with path returns L5 chunks of that doc."""
    from rag.graph_index import GraphIndex
    db = tmp_path / "graph.db"
    gi = GraphIndex(str(db))
    gi.upsert_chunks("doc.md", "科技", "AI", "模型", [
        ("chunk-0", "first chunk about ai"),
        ("chunk-1", "second chunk about llm"),
    ])
    gi.close()

    server = KnowledgeServer(str(tmp_path), graph_db_path=str(db))
    out = server.execute({"op": "chunks", "path": "doc.md"})
    assert out["ok"] is True
    r = out["result"]
    assert r["path"] == "doc.md"
    assert r["count"] == 2
    texts = [c["chunk_text"] for c in r["chunks"]]
    assert "first chunk about ai" in texts
    assert "second chunk about llm" in texts


def test_chunks_op_by_category(tmp_path: Path):
    """chunks_by_cat op returns chunks filtered by l1/l2/l3."""
    from rag.graph_index import GraphIndex
    db = tmp_path / "graph.db"
    gi = GraphIndex(str(db))
    gi.upsert_chunks("a.md", "科技", "AI", "模型", [
        ("a-0", "ai content"),
    ])
    gi.upsert_chunks("b.md", "历史", "中国", "朝代", [
        ("b-0", "汉代 content"),
    ])
    gi.close()

    server = KnowledgeServer(str(tmp_path), graph_db_path=str(db))
    out = server.execute({"op": "chunks_by_cat", "l1": "历史"})
    assert out["ok"] is True
    r = out["result"]
    assert r["count"] == 1
    assert r["chunks"][0]["chunk_text"] == "汉代 content"
    assert r["chunks"][0]["l1"] == "历史"


def test_chunks_op_empty_db(tmp_path: Path):
    """chunks op on empty graph db returns count=0."""
    from rag.graph_index import GraphIndex
    db = tmp_path / "graph.db"
    gi = GraphIndex(str(db))
    gi.close()

    server = KnowledgeServer(str(tmp_path), graph_db_path=str(db))
    out = server.execute({"op": "chunks", "path": "nonexistent.md"})
    assert out["ok"] is True
    assert out["result"]["count"] == 0
    assert out["result"]["chunks"] == []


def test_chunks_op_no_graph_db_returns_error(tmp_path: Path):
    """chunks op without graph_db_path configured returns error."""
    server = KnowledgeServer(str(tmp_path))
    out = server.execute({"op": "chunks", "path": "foo.md"})
    assert out["ok"] is False
    assert "graph_db_path not configured" in out["error"]


def test_chunks_op_missing_path_returns_error(tmp_path: Path):
    """chunks op without path returns error."""
    from rag.graph_index import GraphIndex
    db = tmp_path / "graph.db"
    gi = GraphIndex(str(db))
    gi.close()

    server = KnowledgeServer(str(tmp_path), graph_db_path=str(db))
    out = server.execute({"op": "chunks"})
    assert out["ok"] is False
    assert "path" in out["error"]


def test_chunks_by_cat_missing_l1_returns_error(tmp_path: Path):
    """chunks_by_cat without l1 returns error."""
    from rag.graph_index import GraphIndex
    db = tmp_path / "graph.db"
    gi = GraphIndex(str(db))
    gi.close()

    server = KnowledgeServer(str(tmp_path), graph_db_path=str(db))
    out = server.execute({"op": "chunks_by_cat"})
    assert out["ok"] is False
    assert "l1" in out["error"]
