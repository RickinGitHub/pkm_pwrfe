"""Phase 7 tests: GraphIndex L5 chunk-level atomic index.

Covers document_chunks table: upsert_chunks, delete_chunks, get_chunks,
count_chunks, cascade delete on parent_path removal, persistence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rag.graph_index import GraphIndex


@pytest.fixture
def gi(tmp_path: Path) -> GraphIndex:
    return GraphIndex(str(tmp_path / "graph.db"))


# ---------------------------------------------------------------------------
# upsert_chunks
# ---------------------------------------------------------------------------

def test_upsert_chunks_inserts_l5_rows(gi: GraphIndex):
    chunks = [("doc.md#0", "first chunk text"), ("doc.md#1", "second chunk text")]
    n = gi.upsert_chunks("doc.md", "科技", "AI", "模型", chunks)
    assert n == 2
    assert gi.count_chunks() == 2
    rows = gi.get_chunks("doc.md")
    assert all(r["level"] == "L5" for r in rows)
    assert all(r["parent_path"] == "doc.md" for r in rows)


def test_upsert_chunks_replaces_on_same_id(gi: GraphIndex):
    gi.upsert_chunks("doc.md", "科技", "AI", "模型", [("c0", "old text")])
    gi.upsert_chunks("doc.md", "科技", "AI", "模型", [("c0", "new text")])
    rows = gi.get_chunks("doc.md")
    assert len(rows) == 1  # INSERT OR REPLACE 覆盖
    assert rows[0]["chunk_text"] == "new text"


def test_upsert_chunks_empty_list_returns_zero(gi: GraphIndex):
    n = gi.upsert_chunks("doc.md", "科技", "AI", "模型", [])
    assert n == 0
    assert gi.count_chunks() == 0


def test_upsert_chunks_inherits_parent_category(gi: GraphIndex):
    gi.upsert_chunks("doc.md", "历史", "中国", "朝代", [("c0", "text")])
    rows = gi.get_chunks("doc.md")
    assert rows[0]["l1"] == "历史"
    assert rows[0]["l2"] == "中国"
    assert rows[0]["l3"] == "朝代"


def test_upsert_chunks_multiple_parents(gi: GraphIndex):
    gi.upsert_chunks("a.md", "科技", "AI", "模型", [("a#0", "a0")])
    gi.upsert_chunks("b.md", "职场", "成长", "策略", [("b#0", "b0")])
    assert gi.count_chunks() == 2
    a = gi.get_chunks("a.md")
    assert len(a) == 1
    assert a[0]["chunk_text"] == "a0"
    b = gi.get_chunks("b.md")
    assert len(b) == 1
    assert b[0]["chunk_text"] == "b0"


# ---------------------------------------------------------------------------
# get_chunks
# ---------------------------------------------------------------------------

def test_get_chunks_returns_ordered_by_chunk_id(gi: GraphIndex):
    chunks = [("doc.md#2", "two"), ("doc.md#0", "zero"), ("doc.md#1", "one")]
    gi.upsert_chunks("doc.md", "科技", "AI", "模型", chunks)
    rows = gi.get_chunks("doc.md")
    ids = [r["chunk_id"] for r in rows]
    assert ids == ["doc.md#0", "doc.md#1", "doc.md#2"]


def test_get_chunks_limit(gi: GraphIndex):
    chunks = [(f"doc.md#{i}", f"text{i}") for i in range(10)]
    gi.upsert_chunks("doc.md", "科技", "AI", "模型", chunks)
    rows = gi.get_chunks("doc.md", limit=3)
    assert len(rows) == 3


def test_get_chunks_empty_for_unknown_parent(gi: GraphIndex):
    assert gi.get_chunks("never_existed.md") == []


def test_get_chunks_returns_full_dict(gi: GraphIndex):
    gi.upsert_chunks("doc.md", "科技", "AI", "模型", [("c0", "text")])
    rows = gi.get_chunks("doc.md")
    r = rows[0]
    assert set(r.keys()) == {
        "chunk_id", "parent_path", "chunk_text", "l1", "l2", "l3", "added_at", "level"
    }


# ---------------------------------------------------------------------------
# delete_chunks
# ---------------------------------------------------------------------------

def test_delete_chunks_by_parent(gi: GraphIndex):
    gi.upsert_chunks("doc.md", "科技", "AI", "模型", [("c0", "a"), ("c1", "b")])
    n = gi.delete_chunks("doc.md")
    assert n == 2
    assert gi.count_chunks() == 0


def test_delete_chunks_returns_zero_for_unknown_parent(gi: GraphIndex):
    n = gi.delete_chunks("never_existed.md")
    assert n == 0


def test_delete_chunks_cascade_on_parent_delete_path(gi: GraphIndex):
    """delete_path(parent) 级联清理 document_chunks。"""
    gi.upsert("doc.md", "科技", "AI", "模型")
    gi.upsert_chunks("doc.md", "科技", "AI", "模型", [("c0", "a"), ("c1", "b")])
    assert gi.count_chunks() == 2

    gi.delete_path("doc.md")  # 级联删除
    assert gi.count_chunks() == 0
    assert not gi.exists("doc.md")


# ---------------------------------------------------------------------------
# count_chunks
# ---------------------------------------------------------------------------

def test_count_chunks_zero_on_empty(gi: GraphIndex):
    assert gi.count_chunks() == 0


def test_count_chunks_after_multiple_upserts(gi: GraphIndex):
    gi.upsert_chunks("a.md", "科技", "AI", "模型", [("a0", "x"), ("a1", "y")])
    gi.upsert_chunks("b.md", "科技", "AI", "模型", [("b0", "z")])
    assert gi.count_chunks() == 3


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------

def test_chunks_persist_across_connections(tmp_path: Path):
    """关闭重开后 chunks 仍在。"""
    db = tmp_path / "graph.db"
    g1 = GraphIndex(str(db))
    g1.upsert_chunks("doc.md", "科技", "AI", "模型", [("c0", "persist me")])
    g1.close()

    g2 = GraphIndex(str(db))
    assert g2.count_chunks() == 1
    rows = g2.get_chunks("doc.md")
    assert rows[0]["chunk_text"] == "persist me"
    g2.close()
