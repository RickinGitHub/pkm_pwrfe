"""Phase 4 tests: multi-category (Multi-homing) + knowledge_edges + wikilinks.

覆盖：
- GraphIndex.upsert_categories / replace_categories / get_categories
- GraphIndex.upsert_edge / neighbors / all_edges
- pipeline_worker.classify_multi（多标签频次加权）
- pipeline_worker.extract_wikilinks / upsert_edges_from_wikilinks
"""

from pathlib import Path

import pytest

from rag.graph_index import GraphIndex
from scripts.pipeline_worker import (
    classify_multi,
    extract_wikilinks,
    upsert_edges_from_wikilinks,
    graph_index_upsert_categories,
    process_file,
)


@pytest.fixture
def gi(tmp_path: Path) -> GraphIndex:
    return GraphIndex(str(tmp_path / "graph.db"))


# ---------------------------------------------------------------------------
# Multi-homing: 同 path 多标签
# ---------------------------------------------------------------------------

def test_upsert_categories_writes_multiple_rows(gi: GraphIndex):
    cats = [("科技", "AI", "模型"), ("职场", "成长", "策略")]
    flags = gi.upsert_categories("a.md", cats)
    assert flags == [True, True]
    assert gi.count() == 2
    assert gi.count_distinct_paths() == 1


def test_upsert_categories_idempotent(gi: GraphIndex):
    cats = [("科技", "AI", "模型")]
    gi.upsert_categories("a.md", cats)
    flags = gi.upsert_categories("a.md", cats)
    assert flags == [False]
    assert gi.count() == 1


def test_replace_categories_removes_old_and_inserts_new(gi: GraphIndex):
    gi.upsert("a.md", "科技", "AI", "模型")
    gi.upsert("a.md", "职场", "成长", "策略")
    assert gi.count() == 2

    new_cats = [("历史", "中国", "朝代")]
    n = gi.replace_categories("a.md", new_cats)
    assert n == 1
    assert gi.count() == 1
    cats = gi.get_categories("a.md")
    assert len(cats) == 1
    assert (cats[0]["l1"], cats[0]["l2"], cats[0]["l3"]) == ("历史", "中国", "朝代")


def test_get_categories_returns_all_tags(gi: GraphIndex):
    gi.upsert("a.md", "科技", "AI", "模型")
    gi.upsert("a.md", "职场", "成长", "策略")
    gi.upsert("a.md", "历史", "中国", "朝代")
    cats = gi.get_categories("a.md")
    assert len(cats) == 3
    tuples = [(c["l1"], c["l2"], c["l3"]) for c in cats]
    assert ("科技", "AI", "模型") in tuples
    assert ("职场", "成长", "策略") in tuples
    assert ("历史", "中国", "朝代") in tuples


def test_count_distinct_paths_with_multi_homing(gi: GraphIndex):
    gi.upsert("a.md", "科技", "AI", "模型")
    gi.upsert("a.md", "历史", "中国", "朝代")
    gi.upsert("b.md", "科技", "AI", "模型")
    assert gi.count() == 3
    assert gi.count_distinct_paths() == 2


def test_filter_returns_all_matching_rows(gi: GraphIndex):
    """Multi-homing: 同 path 在多个分类下时，filter 返回多行。"""
    gi.upsert("a.md", "科技", "AI", "模型")
    gi.upsert("a.md", "历史", "中国", "朝代")
    rows = gi.filter(l1="科技")
    assert len(rows) == 1
    rows = gi.filter(l1="历史")
    assert len(rows) == 1
    # 无过滤返回全部 2 行
    rows = gi.filter()
    assert len(rows) == 2


def test_list_paths_dedupes_multi_homing(gi: GraphIndex):
    gi.upsert("a.md", "科技", "AI", "模型")
    gi.upsert("a.md", "历史", "中国", "朝代")
    gi.upsert("b.md", "科技", "AI", "模型")
    paths = gi.list_paths(l1="科技")
    assert paths == ["a.md", "b.md"]  # a.md 只出现一次
    paths_all = gi.list_paths()
    assert sorted(paths_all) == ["a.md", "b.md"]


# ---------------------------------------------------------------------------
# knowledge_edges
# ---------------------------------------------------------------------------

def test_upsert_edge_creates_new_edge(gi: GraphIndex):
    added = gi.upsert_edge("a.md", "b.md")
    assert added is True
    assert gi.edges_count() == 1


def test_upsert_edge_idempotent(gi: GraphIndex):
    gi.upsert_edge("a.md", "b.md", weight=0.5)
    added = gi.upsert_edge("a.md", "b.md", weight=0.9, rel_type="strong")
    assert added is False  # 已存在，仅更新
    edges = gi.all_edges()
    assert edges[0]["weight"] == 0.9
    assert edges[0]["rel_type"] == "strong"


def test_upsert_edge_rejects_self_loop(gi: GraphIndex):
    added = gi.upsert_edge("a.md", "a.md")
    assert added is False
    assert gi.edges_count() == 0


def test_delete_edge(gi: GraphIndex):
    gi.upsert_edge("a.md", "b.md")
    n = gi.delete_edge("a.md", "b.md")
    assert n == 1
    assert gi.edges_count() == 0
    # 删除不存在的 edge 返回 0
    n = gi.delete_edge("a.md", "b.md")
    assert n == 0


def test_neighbors_out_direction(gi: GraphIndex):
    gi.upsert_edge("a.md", "b.md")
    gi.upsert_edge("a.md", "c.md")
    gi.upsert_edge("b.md", "a.md")  # 反向
    neighbors = gi.neighbors("a.md", direction="out")
    paths = {n["path"] for n in neighbors}
    assert paths == {"b.md", "c.md"}


def test_neighbors_in_direction(gi: GraphIndex):
    gi.upsert_edge("a.md", "b.md")
    gi.upsert_edge("c.md", "b.md")
    neighbors = gi.neighbors("b.md", direction="in")
    paths = {n["path"] for n in neighbors}
    assert paths == {"a.md", "c.md"}


def test_neighbors_both_direction_dedupes(gi: GraphIndex):
    gi.upsert_edge("a.md", "b.md")
    gi.upsert_edge("b.md", "a.md")
    neighbors = gi.neighbors("a.md", direction="both")
    paths = {n["path"] for n in neighbors}
    assert paths == {"b.md"}  # deduped


def test_neighbors_filter_by_rel_type(gi: GraphIndex):
    gi.upsert_edge("a.md", "b.md", rel_type="wikilink")
    gi.upsert_edge("a.md", "c.md", rel_type="manual")
    neighbors = gi.neighbors("a.md", direction="out", rel_type="wikilink")
    assert len(neighbors) == 1
    assert neighbors[0]["path"] == "b.md"


def test_delete_path_cascades_to_edges(gi: GraphIndex):
    gi.upsert("a.md", "科技", "AI", "模型")
    gi.upsert("b.md", "科技", "AI", "模型")
    gi.upsert_edge("a.md", "b.md")
    gi.upsert_edge("b.md", "a.md")
    assert gi.edges_count() == 2

    gi.delete_path("a.md")
    # a.md 删除后，两端相关 edge 都应消失
    assert gi.edges_count() == 0


def test_all_edges_returns_full_list(gi: GraphIndex):
    gi.upsert_edge("a.md", "b.md", weight=0.5, rel_type="wikilink")
    gi.upsert_edge("b.md", "c.md", weight=1.0, rel_type="related")
    edges = gi.all_edges()
    assert len(edges) == 2
    assert edges[0]["source_path"] == "a.md"


# ---------------------------------------------------------------------------
# classify_multi — 多标签频次加权
# ---------------------------------------------------------------------------

_RULES = {
    "defaults": {"l1": "未分类", "l2": "Misc", "l3": "General"},
    "rules": [
        {"l1": "科技", "l2": "AI", "l3": "模型", "keywords": ["ai", "llm", "gpt"]},
        {"l1": "科技", "l2": "AI", "l3": "研发体系", "keywords": ["coding", "devops", "agent"]},
        {"l1": "职场", "l2": "成长", "l3": "策略", "keywords": ["职业", "简历", "晋升"]},
        {"l1": "历史", "l2": "中国", "l3": "朝代", "keywords": ["汉代", "明代", "资治通鉴"]},
    ],
}


def test_classify_multi_returns_multiple_labels():
    """文档命中多个规则时，返回多个标签按频次排序。"""
    title = "AI 历史交叉研究"
    content = "llm gpt 汉代 资治通鉴 ai coding agent"
    labels = classify_multi(title, content, _RULES, max_labels=3)
    assert len(labels) >= 2
    label_tuples = [(l[0], l[1], l[2]) for l in labels]
    assert ("科技", "AI", "模型") in label_tuples  # ai/llm/gpt 命中
    assert ("科技", "AI", "研发体系") in label_tuples  # coding/agent 命中
    assert ("历史", "中国", "朝代") in label_tuples  # 汉代/资治通鉴 命中


def test_classify_multi_sorted_by_score_descending():
    title = "AI 主题"
    content = "ai ai ai llm gpt"  # 模型规则命中 5 次
    labels = classify_multi(title, content, _RULES, max_labels=3)
    assert len(labels) == 1
    assert labels[0][:3] == ("科技", "AI", "模型")


def test_classify_multi_caps_at_max_labels():
    title = "Multi-topic"
    content = "ai llm gpt coding devops agent 职业 简历 晋升 汉代 资治通鉴"
    labels = classify_multi(title, content, _RULES, max_labels=2)
    assert len(labels) == 2


def test_classify_multi_returns_defaults_on_no_match():
    title = "unrelated"
    content = "totally unrelated content about cooking"
    labels = classify_multi(title, content, _RULES)
    assert len(labels) == 1
    assert labels[0][:3] == ("未分类", "Misc", "General")


def test_classify_multi_empty_input_returns_defaults():
    labels = classify_multi("", "", _RULES)
    assert len(labels) == 1
    assert labels[0][:3] == ("未分类", "Misc", "General")


# ---------------------------------------------------------------------------
# extract_wikilinks + upsert_edges_from_wikilinks
# ---------------------------------------------------------------------------

def test_extract_wikilinks_basic():
    text = "see [[AI Overview]] and [[History Notes]] for more"
    links = extract_wikilinks(text)
    assert links == ["AI Overview", "History Notes"]


def test_extract_wikilinks_with_display_text():
    """[[display|target]] syntax → returns target."""
    text = "see [[AI 概览|ai-overview]] for details"
    links = extract_wikilinks(text)
    assert links == ["ai-overview"]


def test_extract_wikilinks_empty():
    assert extract_wikilinks("no links here") == []
    assert extract_wikilinks("") == []


def test_extract_wikilinks_multiple_same_target():
    text = "[[foo]] and [[foo]] again"
    links = extract_wikilinks(text)
    assert links == ["foo", "foo"]


def test_upsert_edges_from_wikilinks_creates_edges(tmp_path: Path):
    """[[wikilink]] 解析后，source → target edge 入库。"""
    db = tmp_path / "graph.db"
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "target.md").write_text("# Target\n", encoding="utf-8")
    (corpus / "source.md").write_text("# Source\n[[target]] here", encoding="utf-8")

    text = (corpus / "source.md").read_text(encoding="utf-8")
    n = upsert_edges_from_wikilinks(
        str(db), str((corpus / "source.md").resolve()), text, corpus_dir=corpus,
    )
    assert n == 1
    gi = GraphIndex(str(db))
    try:
        assert gi.edges_count() == 1
        edges = gi.all_edges()
        assert edges[0]["source_path"] == str((corpus / "source.md").resolve())
        assert edges[0]["target_path"] == str((corpus / "target.md").resolve())
        assert edges[0]["rel_type"] == "wikilink"
    finally:
        gi.close()


def test_upsert_edges_skips_self_loop(tmp_path: Path):
    """文档 [[self]] 不应创建自环 edge。"""
    db = tmp_path / "graph.db"
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    src = corpus / "self.md"
    src.write_text("# Self\n[[self]] reference", encoding="utf-8")
    text = src.read_text(encoding="utf-8")
    n = upsert_edges_from_wikilinks(str(db), str(src.resolve()), text, corpus_dir=corpus)
    assert n == 0
    gi = GraphIndex(str(db))
    try:
        assert gi.edges_count() == 0
    finally:
        gi.close()


def test_upsert_edges_unresolvable_target_skipped(tmp_path: Path):
    """[[nonexistent]] 找不到对应文件时跳过（不入 edge）。"""
    db = tmp_path / "graph.db"
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    src = corpus / "src.md"
    src.write_text("# Src\n[[nonexistent]] here", encoding="utf-8")
    text = src.read_text(encoding="utf-8")
    n = upsert_edges_from_wikilinks(str(db), str(src.resolve()), text, corpus_dir=corpus)
    assert n == 0


def test_upsert_edges_idempotent_on_rerun(tmp_path: Path):
    """相同 wikilinks 多次调用，edges_count 不增长。"""
    db = tmp_path / "graph.db"
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "target.md").write_text("# Target\n", encoding="utf-8")
    src = corpus / "source.md"
    src.write_text("# Source\n[[target]]", encoding="utf-8")
    text = src.read_text(encoding="utf-8")

    n1 = upsert_edges_from_wikilinks(str(db), str(src.resolve()), text, corpus_dir=corpus)
    n2 = upsert_edges_from_wikilinks(str(db), str(src.resolve()), text, corpus_dir=corpus)
    assert n1 == 1
    assert n2 == 0  # 已存在，未新增

    gi = GraphIndex(str(db))
    try:
        assert gi.edges_count() == 1
    finally:
        gi.close()


# ---------------------------------------------------------------------------
# process_file 集成：multi-homing + wikilinks 一起跑
# ---------------------------------------------------------------------------

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
  - l1: 历史
    l2: 中国
    l3: 朝代
    keywords: [汉代, 资治通鉴, 明代]
"""


def test_process_file_writes_multi_category_and_wikilink_edges(tmp_path: Path):
    rules_path = tmp_path / "tag_rules.yaml"
    rules_path.write_text(_RULES_YAML, encoding="utf-8")
    fts_db = tmp_path / "fts.db"
    graph_db = tmp_path / "graph.db"
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    # 创建一个目标文档
    target = corpus / "target.md"
    target.write_text("# 汉代历史\n\n资治通鉴记载。", encoding="utf-8")

    # 创建一个同时命中 AI 和 历史 规则的文档，并 wikilink 到 target
    doc = corpus / "doc.md"
    doc.write_text(
        "# AI 与历史\n\n本文讨论 ai llm gpt 与汉代 资治通鉴 的交叉。详见 [[target]]。",
        encoding="utf-8",
    )

    out = process_file(
        doc,
        rules_path=rules_path,
        fts_path=fts_db,
        graph_db_path=graph_db,
    )
    assert out["ok"] is True
    r = out["result"]
    # Multi-homing: 至少 2 个分类
    assert len(r["categories"]) >= 2
    cat_tuples = [(c["l1"], c["l2"], c["l3"]) for c in r["categories"]]
    assert ("科技", "AI", "模型") in cat_tuples
    assert ("历史", "中国", "朝代") in cat_tuples
    # Wikilink edge
    assert r["edges_added"] >= 1

    # 校验 graph_index 状态
    gi = GraphIndex(str(graph_db))
    try:
        cats = gi.get_categories(str(doc.resolve()))
        assert len(cats) >= 2
        # target.md 还没 process_file，但 wikilink edge 仍应存在（target 文件已物理存在）
        neighbors = gi.neighbors(str(doc.resolve()), direction="out")
        target_paths = {n["path"] for n in neighbors}
        assert str(target.resolve()) in target_paths
    finally:
        gi.close()


# ---------------------------------------------------------------------------
# Phase 4 wikilink codeblock protection — wikilinks inside ```code blocks```
# should NOT be parsed.
# ---------------------------------------------------------------------------

def test_wikilinks_inside_codeblocks_not_parsed(tmp_path: Path):
    """Wikilinks inside ```code blocks``` should NOT create edges."""
    from scripts.pipeline_worker import clean_md
    db = tmp_path / "graph.db"
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    # real-target exists, fake-inside-code and also-fake do not
    (corpus / "real-target.md").write_text("# Real Target\n", encoding="utf-8")
    src = corpus / "source.md"
    src.write_text(
        "# Codeblock Test\n\n"
        "正文 [[real-target]] 应建边。\n\n"
        "```python\n"
        "# 这里的 [[fake-inside-code]] 不应建边\n"
        'config = {"key": "[[also-fake]]"}\n'
        "```\n",
        encoding="utf-8",
    )
    raw = src.read_text(encoding="utf-8")
    stashed = clean_md(raw, keep_codeblocks_stashed=True)
    # stashed text should still contain the real-target wikilink
    assert "[[real-target]]" in stashed
    # stashed text should NOT contain codeblock wikilinks (they're now \x00CODEBLOCK{n}\x00)
    assert "fake-inside-code" not in stashed
    assert "also-fake" not in stashed

    n = upsert_edges_from_wikilinks(str(db), str(src.resolve()), stashed, corpus_dir=corpus)
    assert n == 1  # only real-target
    gi = GraphIndex(str(db))
    try:
        edges = gi.all_edges()
        targets = {e["target_path"] for e in edges}
        assert str((corpus / "real-target.md").resolve()) in targets
        # fake-inside-code and also-fake should not appear as edges
        for e in edges:
            assert "fake-inside-code" not in e["target_path"]
            assert "also-fake" not in e["target_path"]
    finally:
        gi.close()


def test_wikilinks_outside_codeblocks_parsed(tmp_path: Path):
    """Wikilinks in regular text (outside code blocks) should still be parsed."""
    from scripts.pipeline_worker import clean_md
    db = tmp_path / "graph.db"
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "bar.md").write_text("# Bar\n", encoding="utf-8")
    src = corpus / "source.md"
    src.write_text(
        "# Mixed\n\n"
        "See [[bar]] in prose.\n\n"
        "```\n[[ignored]]\n```\n",
        encoding="utf-8",
    )
    raw = src.read_text(encoding="utf-8")
    stashed = clean_md(raw, keep_codeblocks_stashed=True)
    links = extract_wikilinks(stashed)
    assert "bar" in links
    assert "ignored" not in links


def test_process_file_does_not_parse_wikilinks_in_codeblocks(tmp_path: Path):
    """End-to-end: process_file should skip wikilinks inside code blocks."""
    db = tmp_path / "graph.db"
    fts_db = tmp_path / "fts.db"
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(_RULES_YAML, encoding="utf-8")

    # real-target exists so its edge should be created
    (corpus / "real-target.md").write_text("# Real\n\nai llm", encoding="utf-8")
    src = corpus / "src.md"
    src.write_text(
        "# Src\n\n"
        "ai llm gpt 文本 [[real-target]] 应建边。\n\n"
        "```python\n"
        "# [[fake-inside-code]] should not be an edge\n"
        "```\n",
        encoding="utf-8",
    )

    out = process_file(
        src,
        rules_path=rules_path,
        fts_path=fts_db,
        graph_db_path=db,
    )
    assert out["ok"] is True
    # Should create exactly 1 edge (real-target), not 2
    assert out["result"]["edges_added"] == 1
    gi = GraphIndex(str(db))
    try:
        edges = gi.all_edges()
        targets = {e["target_path"] for e in edges}
        assert str((corpus / "real-target.md").resolve()) in targets
        for e in edges:
            assert "fake-inside-code" not in e["target_path"]
    finally:
        gi.close()
