"""Tests for rag.graph_index.GraphIndex — SQLite-backed L1/L2/L3/L4 document graph.

Phase 2: replaces the old config/index.yaml + threading.Lock approach with
SQLite WAL mode for native concurrent-write safety.
"""

import threading
import time
from pathlib import Path

import pytest

from rag.graph_index import GraphIndex


@pytest.fixture
def gi(tmp_path: Path) -> GraphIndex:
    return GraphIndex(str(tmp_path / "graph.db"))


def test_upsert_inserts_new_row(gi: GraphIndex):
    added = gi.upsert("a.md", "科技", "AI", "模型")
    assert added is True
    assert gi.count() == 1


def test_upsert_is_idempotent_on_same_path(gi: GraphIndex):
    gi.upsert("a.md", "科技", "AI", "模型")
    added = gi.upsert("a.md", "科技", "AI", "模型")
    assert added is False
    assert gi.count() == 1


def test_upsert_updates_l1_l2_l3_on_path_change(gi: GraphIndex):
    """Phase 4 行为变更：Multi-homing 允许同 path 多标签。
    同 path 调用 upsert 不同 (l1,l2,l3) 会产生多行（而非覆盖）。
    get_categories 返回所有标签；get 返回首个（向后兼容）。
    """
    gi.upsert("a.md", "科技", "AI", "模型")
    gi.upsert("a.md", "职场", "成长", "策略")
    # Multi-homing: 2 rows
    assert gi.count() == 2
    cats = gi.get_categories("a.md")
    assert len(cats) == 2
    cat_tuples = [(c["l1"], c["l2"], c["l3"]) for c in cats]
    assert ("科技", "AI", "模型") in cat_tuples
    assert ("职场", "成长", "策略") in cat_tuples


def test_get_returns_none_for_missing_path(gi: GraphIndex):
    assert gi.get("nope.md") is None


def test_get_returns_full_node(gi: GraphIndex):
    gi.upsert("a.md", "科技", "AI", "模型", added_at="2026-01-01T00:00:00")
    node = gi.get("a.md")
    assert node == {
        "path": "a.md",
        "l1": "科技",
        "l2": "AI",
        "l3": "模型",
        "added_at": "2026-01-01T00:00:00",
        "level": "L4",
    }


def test_exists(gi: GraphIndex):
    assert gi.exists("a.md") is False
    gi.upsert("a.md", "科技", "AI", "模型")
    assert gi.exists("a.md") is True


def test_delete_removes_row(gi: GraphIndex):
    gi.upsert("a.md", "科技", "AI", "模型")
    gi.upsert("b.md", "职场", "成长", "策略")
    n = gi.delete("a.md")
    assert n == 1
    assert gi.count() == 1
    assert not gi.exists("a.md")


def test_delete_missing_path_returns_zero(gi: GraphIndex):
    n = gi.delete("nope.md")
    assert n == 0


def test_filter_by_l1(gi: GraphIndex):
    gi.upsert("a.md", "科技", "AI", "模型")
    gi.upsert("b.md", "科技", "AI", "研发体系")
    gi.upsert("c.md", "职场", "成长", "策略")
    rows = gi.filter(l1="科技")
    assert len(rows) == 2
    assert all(r["l1"] == "科技" for r in rows)


def test_filter_by_l1_l2_l3(gi: GraphIndex):
    gi.upsert("a.md", "科技", "AI", "模型")
    gi.upsert("b.md", "科技", "AI", "研发体系")
    gi.upsert("c.md", "科技", "AI", "模型")
    rows = gi.filter(l1="科技", l2="AI", l3="模型")
    paths = {r["path"] for r in rows}
    assert paths == {"a.md", "c.md"}


def test_filter_limit(gi: GraphIndex):
    for i in range(10):
        gi.upsert(f"f{i}.md", "科技", "AI", "模型")
    rows = gi.filter(l1="科技", limit=3)
    assert len(rows) == 3


def test_count_zero_on_empty(gi: GraphIndex):
    assert gi.count() == 0


def test_tree_builds_nested_dict(gi: GraphIndex):
    gi.upsert("a.md", "科技", "AI", "模型")
    gi.upsert("b.md", "科技", "AI", "模型")
    gi.upsert("c.md", "职场", "成长", "策略")
    tree = gi.tree()
    assert "科技" in tree
    assert "AI" in tree["科技"]
    assert "模型" in tree["科技"]["AI"]
    assert len(tree["科技"]["AI"]["模型"]) == 2
    assert "职场" in tree
    assert "成长" in tree["职场"]
    assert "策略" in tree["职场"]["成长"]
    assert len(tree["职场"]["成长"]["策略"]) == 1


def test_tree_empty_when_no_rows(gi: GraphIndex):
    assert gi.tree() == {}


def test_export_yaml_dict_has_version_and_tree(gi: GraphIndex):
    gi.upsert("a.md", "科技", "AI", "模型")
    data = gi.export_yaml_dict()
    assert data["version"] == 1
    assert "tree" in data
    assert "科技" in data["tree"]


def test_concurrent_writes_do_not_lose_entries(tmp_path: Path):
    """SQLite WAL 应保证多线程并发写入无丢失（替代旧的 threading.Lock + atomic replace）。

    迁移单例锁 + 短暂 sleep 让首个 worker 完成迁移后再并发 upsert，
    避免边迁移边写入的极端时序。
    """
    db_path = tmp_path / "graph.db"
    paths = [f"file_{i}.md" for i in range(30)]

    # 先在主线程触发一次迁移，确保 schema 就位
    gi_init = GraphIndex(str(db_path))
    gi_init.close()
    # 等待 WAL 落盘
    time.sleep(0.1)

    def worker(p: str) -> None:
        gi = GraphIndex(str(db_path))
        try:
            gi.upsert(p, "科技", "AI", "模型")
        finally:
            gi.close()

    threads = [threading.Thread(target=worker, args=(p,)) for p in paths]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    gi = GraphIndex(str(db_path))
    try:
        assert gi.count() == 30
        got = {r["path"] for r in gi.filter(l1="科技", limit=100)}
        assert got == set(paths)
    finally:
        gi.close()


def test_concurrent_upserts_and_deletes_do_not_deadlock(tmp_path: Path):
    """Mix of inserts + deletes across threads must not deadlock (SQLite WAL)."""
    db_path = tmp_path / "graph.db"
    gi = GraphIndex(str(db_path))
    for i in range(20):
        gi.upsert(f"f{i}.md", "科技", "AI", "模型")
    gi.close()

    errors: list[Exception] = []

    def inserter():
        try:
            g = GraphIndex(str(db_path))
            for i in range(20, 40):
                g.upsert(f"f{i}.md", "科技", "AI", "模型")
            g.close()
        except Exception as e:
            errors.append(e)

    def deleter():
        try:
            g = GraphIndex(str(db_path))
            for i in range(0, 20):
                g.delete(f"f{i}.md")
            g.close()
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=inserter)
    t2 = threading.Thread(target=deleter)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert errors == []


def test_close_does_not_raise(gi: GraphIndex):
    gi.close()


def test_persists_across_connections(tmp_path: Path):
    """数据写入后，新 connection 应能读到（验证 SQLite 持久化）。"""
    db_path = tmp_path / "graph.db"
    g1 = GraphIndex(str(db_path))
    g1.upsert("a.md", "科技", "AI", "模型")
    g1.close()

    g2 = GraphIndex(str(db_path))
    assert g2.count() == 1
    assert g2.exists("a.md")
    g2.close()
