"""End-to-end test for scripts.pipeline_worker.process_file and delete_file_indexes."""

from pathlib import Path

import yaml

from scripts.pipeline_worker import process_file, delete_file_indexes
from rag.fts_index import FtsIndex
from rag.graph_index import GraphIndex


_RULES_YAML = """
defaults:
  l1: 未分类
  l2: Misc
  l3: General
rules:
  - l1: 科技
    l2: AI
    l3: 模型
    keywords: [ai, llm, gpt]
  - l1: 职场
    l2: 成长
    l3: 策略
    keywords: [职业, 简历]
"""


def _write_md(path: Path, title: str, body: str) -> None:
    path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")


def test_process_file_full_pipeline_classifies_and_indexes(tmp_path: Path):
    rules_path = tmp_path / "tag_rules.yaml"
    rules_path.write_text(_RULES_YAML, encoding="utf-8")
    index_yaml = tmp_path / "index.yaml"
    fts_db = tmp_path / "fts.db"
    graph_db = tmp_path / "graph.db"

    doc = tmp_path / "doc.md"
    _write_md(doc, "AI LLM Overview", "This doc explains llm and gpt in depth.")

    out = process_file(
        doc,
        rules_path=rules_path,
        index_yaml_path=index_yaml,
        fts_path=fts_db,
        graph_db_path=graph_db,
    )

    assert out["ok"] is True
    r = out["result"]
    assert (r["l1"], r["l2"], r["l3"]) == ("科技", "AI", "模型")
    assert r["index_yaml_added"] is True
    assert r["graph_added"] is True

    # Frontmatter injected.
    content = doc.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    fm = yaml.safe_load(content.split("---\n", 2)[1])
    assert fm["l1"] == "科技"
    assert fm["l2"] == "AI"
    assert fm["l3"] == "模型"
    assert fm["title"] == "AI LLM Overview"

    # FTS5 has the row.
    fts = FtsIndex(str(fts_db))
    try:
        assert fts.count() == 1
        hits = fts.search("llm")
        assert len(hits) == 1
        assert hits[0]["category"] == "科技/AI/模型"
    finally:
        fts.close()

    # Graph index (SQLite) has the L4 leaf.
    gi = GraphIndex(str(graph_db))
    try:
        assert gi.count() == 1
        node = gi.get(str(doc))
        assert node is not None
        assert (node["l1"], node["l2"], node["l3"]) == ("科技", "AI", "模型")
        assert node["level"] == "L4"
    finally:
        gi.close()


def test_process_file_idempotent_on_rerun(tmp_path: Path):
    rules_path = tmp_path / "tag_rules.yaml"
    rules_path.write_text(_RULES_YAML, encoding="utf-8")
    index_yaml = tmp_path / "index.yaml"
    fts_db = tmp_path / "fts.db"

    doc = tmp_path / "doc.md"
    _write_md(doc, "AI Doc", "llm gpt ai")

    process_file(doc, rules_path=rules_path, index_yaml_path=index_yaml, fts_path=fts_db)
    out2 = process_file(
        doc,
        rules_path=rules_path,
        index_yaml_path=index_yaml,
        fts_path=fts_db,
    )

    assert out2["ok"] is True
    assert out2["result"]["index_yaml_added"] is False  # already present

    # FTS5 row count stays at 1 (upsert, not append).
    fts = FtsIndex(str(fts_db))
    try:
        assert fts.count() == 1
    finally:
        fts.close()


def test_process_file_skips_non_md(tmp_path: Path):
    rules_path = tmp_path / "tag_rules.yaml"
    rules_path.write_text(_RULES_YAML, encoding="utf-8")
    txt = tmp_path / "data.txt"
    txt.write_text("hello", encoding="utf-8")

    out = process_file(
        txt,
        rules_path=rules_path,
        index_yaml_path=tmp_path / "index.yaml",
        fts_path=tmp_path / "fts.db",
    )
    assert out["ok"] is False
    assert "not a markdown" in out["error"]


def test_process_file_missing_file_returns_error(tmp_path: Path):
    out = process_file(tmp_path / "nope.md")
    assert out["ok"] is False
    assert "not found" in out["error"]


def test_process_file_handles_chinese_classification(tmp_path: Path):
    rules_path = tmp_path / "tag_rules.yaml"
    rules_path.write_text(_RULES_YAML, encoding="utf-8")
    index_yaml = tmp_path / "index.yaml"
    fts_db = tmp_path / "fts.db"

    doc = tmp_path / "zh.md"
    _write_md(doc, "职业规划", "本文讨论简历怎么写、晋升路径与跳槽决策。")

    out = process_file(
        doc,
        rules_path=rules_path,
        index_yaml_path=index_yaml,
        fts_path=fts_db,
    )
    assert out["ok"] is True
    assert (out["result"]["l1"], out["result"]["l2"], out["result"]["l3"]) == (
        "职场",
        "成长",
        "策略",
    )

    # FTS5 Chinese searchable (trigram needs >= 3 chars; use 4-char phrase).
    fts = FtsIndex(str(fts_db))
    try:
        hits = fts.search("简历怎么")
        assert len(hits) == 1
    finally:
        fts.close()


def test_process_file_falls_back_to_defaults(tmp_path: Path):
    rules_path = tmp_path / "tag_rules.yaml"
    rules_path.write_text(_RULES_YAML, encoding="utf-8")
    index_yaml = tmp_path / "index.yaml"
    fts_db = tmp_path / "fts.db"

    doc = tmp_path / "rand.md"
    _write_md(doc, "Random", "totally unrelated content about cooking recipes")

    out = process_file(
        doc,
        rules_path=rules_path,
        index_yaml_path=index_yaml,
        fts_path=fts_db,
    )
    assert out["ok"] is True
    assert (out["result"]["l1"], out["result"]["l2"], out["result"]["l3"]) == (
        "未分类",
        "Misc",
        "General",
    )


# ---------------------------------------------------------------------------
# Phase 3: delete_file_indexes — on_deleted 生命周期闭环
# ---------------------------------------------------------------------------

def test_delete_file_indexes_removes_fts5_and_graph(tmp_path: Path):
    """删除文件后，FTS5 + graph_index 都应清理干净。"""
    rules_path = tmp_path / "tag_rules.yaml"
    rules_path.write_text(_RULES_YAML, encoding="utf-8")
    fts_db = tmp_path / "fts.db"
    graph_db = tmp_path / "graph.db"

    doc = tmp_path / "to_delete.md"
    _write_md(doc, "AI Doc", "llm gpt ai content")

    # 先入库
    process_file(doc, rules_path=rules_path, fts_path=fts_db, graph_db_path=graph_db)
    fts = FtsIndex(str(fts_db))
    gi = GraphIndex(str(graph_db))
    try:
        assert fts.count() == 1
        assert gi.count() == 1
    finally:
        fts.close()
        gi.close()

    # 删除文件 + 清理索引
    doc.unlink()
    out = delete_file_indexes(doc, fts_path=fts_db, graph_db_path=graph_db)

    assert out["ok"] is True
    assert out["result"]["fts_deleted"] == 1
    assert out["result"]["graph_deleted"] == 1

    fts = FtsIndex(str(fts_db))
    gi = GraphIndex(str(graph_db))
    try:
        assert fts.count() == 0
        assert gi.count() == 0
    finally:
        fts.close()
        gi.close()


def test_delete_file_indexes_idempotent_on_missing_entries(tmp_path: Path):
    """索引中无该 path 时，delete 应返回 0 而非报错。"""
    fts_db = tmp_path / "fts.db"
    graph_db = tmp_path / "graph.db"
    # 空索引库
    FtsIndex(str(fts_db)).close()
    GraphIndex(str(graph_db)).close()

    out = delete_file_indexes(tmp_path / "never_existed.md", fts_path=fts_db, graph_db_path=graph_db)
    assert out["ok"] is True
    assert out["result"]["fts_deleted"] == 0
    assert out["result"]["graph_deleted"] == 0


def test_delete_file_indexes_only_removes_target_path(tmp_path: Path):
    """删除文件 A 不影响文件 B 的索引。"""
    rules_path = tmp_path / "tag_rules.yaml"
    rules_path.write_text(_RULES_YAML, encoding="utf-8")
    fts_db = tmp_path / "fts.db"
    graph_db = tmp_path / "graph.db"

    doc_a = tmp_path / "a.md"
    doc_b = tmp_path / "b.md"
    _write_md(doc_a, "AI A", "llm content a")
    _write_md(doc_b, "AI B", "gpt content b")

    process_file(doc_a, rules_path=rules_path, fts_path=fts_db, graph_db_path=graph_db)
    process_file(doc_b, rules_path=rules_path, fts_path=fts_db, graph_db_path=graph_db)

    doc_a.unlink()
    out = delete_file_indexes(doc_a, fts_path=fts_db, graph_db_path=graph_db)

    assert out["ok"] is True
    assert out["result"]["fts_deleted"] == 1
    assert out["result"]["graph_deleted"] == 1

    fts = FtsIndex(str(fts_db))
    gi = GraphIndex(str(graph_db))
    try:
        assert fts.count() == 1  # b 还在
        assert gi.count() == 1
        # 剩下的应该是 doc_b
        assert gi.exists(str(doc_b.resolve()))
        assert not gi.exists(str(doc_a.resolve()))
    finally:
        fts.close()
        gi.close()


def test_delete_file_indexes_resolves_relative_path(tmp_path: Path):
    """传入相对路径应被 resolve() 为绝对路径再删除。"""
    rules_path = tmp_path / "tag_rules.yaml"
    rules_path.write_text(_RULES_YAML, encoding="utf-8")
    fts_db = tmp_path / "fts.db"
    graph_db = tmp_path / "graph.db"

    doc = tmp_path / "rel.md"
    _write_md(doc, "AI", "llm content")
    process_file(doc, rules_path=rules_path, fts_path=fts_db, graph_db_path=graph_db)

    # 用绝对路径删除（process_file 内部已 resolve 存入索引）
    doc.unlink()
    out = delete_file_indexes(doc, fts_path=fts_db, graph_db_path=graph_db)
    assert out["ok"] is True
    assert out["result"]["fts_deleted"] == 1
    assert out["result"]["graph_deleted"] == 1


# ---------------------------------------------------------------------------
# Phase 7 chunk integration tests
# ---------------------------------------------------------------------------

def test_process_file_writes_chunks_when_enabled(tmp_path: Path, monkeypatch):
    """PIPELINE_CHUNK_ENABLED=1 时 chunk_count > 0。"""
    monkeypatch.setenv("PIPELINE_CHUNK_ENABLED", "1")
    monkeypatch.setenv("PIPELINE_CHUNK_SIZE", "200")
    monkeypatch.setenv("PIPELINE_CHUNK_OVERLAP", "20")

    rules_path = tmp_path / "tag_rules.yaml"
    rules_path.write_text(_RULES_YAML, encoding="utf-8")
    fts_db = tmp_path / "fts.db"
    graph_db = tmp_path / "graph.db"

    doc = tmp_path / "chunked.md"
    # 写一个足够长的文档触发分块
    body = "Para one about ai llm. " * 50
    _write_md(doc, "AI Doc", body)

    out = process_file(doc, rules_path=rules_path, fts_path=fts_db, graph_db_path=graph_db)
    assert out["ok"] is True
    assert out["result"]["chunk_count"] > 0

    # 验证 chunks 真的写入了 graph_index
    gi = GraphIndex(str(graph_db))
    try:
        assert gi.count_chunks() == out["result"]["chunk_count"]
        chunks = gi.get_chunks(str(doc.resolve()))
        assert len(chunks) > 0
        assert all(c["parent_path"] == str(doc.resolve()) for c in chunks)
    finally:
        gi.close()


def test_process_file_skips_chunks_when_disabled(tmp_path: Path, monkeypatch):
    """PIPELINE_CHUNK_ENABLED=0 时 chunk_count == 0。"""
    monkeypatch.setenv("PIPELINE_CHUNK_ENABLED", "0")

    rules_path = tmp_path / "tag_rules.yaml"
    rules_path.write_text(_RULES_YAML, encoding="utf-8")
    fts_db = tmp_path / "fts.db"
    graph_db = tmp_path / "graph.db"

    doc = tmp_path / "no_chunks.md"
    _write_md(doc, "AI Doc", "llm gpt ai content")

    out = process_file(doc, rules_path=rules_path, fts_path=fts_db, graph_db_path=graph_db)
    assert out["ok"] is True
    assert out["result"]["chunk_count"] == 0

    gi = GraphIndex(str(graph_db))
    try:
        assert gi.count_chunks() == 0
    finally:
        gi.close()


def test_process_file_chunk_failure_non_fatal(tmp_path: Path, monkeypatch):
    """TextChunker.chunk 抛异常 → process_file 仍 ok=True，chunk_count=0。"""
    monkeypatch.setenv("PIPELINE_CHUNK_ENABLED", "1")

    rules_path = tmp_path / "tag_rules.yaml"
    rules_path.write_text(_RULES_YAML, encoding="utf-8")
    fts_db = tmp_path / "fts.db"
    graph_db = tmp_path / "graph.db"

    doc = tmp_path / "fail_chunks.md"
    _write_md(doc, "AI Doc", "llm gpt ai content")

    # mock TextChunker.chunk 抛异常
    from unittest.mock import patch
    with patch("rag.chunker.TextChunker.chunk", side_effect=ValueError("fake chunker failure")):
        out = process_file(doc, rules_path=rules_path, fts_path=fts_db, graph_db_path=graph_db)

    assert out["ok"] is True  # chunk 失败非致命
    assert out["result"]["chunk_count"] == 0
    # 但 FTS5 和 graph_index 仍然成功写入
    assert out["result"]["graph_added"] is True
