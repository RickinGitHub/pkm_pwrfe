# -*- coding: utf-8 -*-
"""PipelineOps.build_similarity_edges op — wraps scripts.build_similarity_edges.build_edges."""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag.graph_index import GraphIndex
from skills.pipeline_ops import PipelineOps


def _write_doc(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_op_build_similarity_edges_basic(tmp_path):
    corpus = tmp_path / "corpus"
    _write_doc(corpus / "a.md", "python web framework django flask")
    _write_doc(corpus / "b.md", "python data analysis pandas numpy")
    _write_doc(corpus / "c.md", "javascript frontend react vue")
    _write_doc(corpus / "d.md", "python web api fastapi starlette")
    graph_db = str(tmp_path / "graph.db")

    skill = PipelineOps()
    out = skill.execute({
        "op": "build_similarity_edges",
        "corpus_dir": str(corpus),
        "graph_db": graph_db,
        "top_k": 2,
    })
    assert out["ok"] is True
    stats = out["result"]
    assert stats["docs"] == 4
    assert stats["edges_added"] > 0
    g = GraphIndex(graph_db)
    assert g.edges_count() > 0


def test_op_build_similarity_edges_clear(tmp_path):
    corpus = tmp_path / "corpus"
    _write_doc(corpus / "a.md", "alpha beta common terms here")
    _write_doc(corpus / "b.md", "alpha beta common words different")
    _write_doc(corpus / "c.md", "alpha beta shared vocabulary again")
    graph_db = str(tmp_path / "graph.db")

    skill = PipelineOps()
    # First run
    out1 = skill.execute({
        "op": "build_similarity_edges",
        "corpus_dir": str(corpus),
        "graph_db": graph_db,
        "top_k": 2,
        "clear": True,
    })
    assert out1["ok"] is True
    first_added = out1["result"]["edges_added"]
    assert first_added > 0

    # Second run with clear: should replace, not accumulate beyond top_k
    out2 = skill.execute({
        "op": "build_similarity_edges",
        "corpus_dir": str(corpus),
        "graph_db": graph_db,
        "top_k": 2,
        "clear": True,
    })
    assert out2["ok"] is True
    # After clear+rebuild, bm25_similar count should equal this run's added (assuming no updates)
    g = GraphIndex(graph_db)
    cnt = g._conn.execute(
        "SELECT COUNT(*) FROM knowledge_edges WHERE rel_type='bm25_similar'"
    ).fetchone()[0]
    assert cnt <= 3 * 2  # 3 docs (minus self) * top_k=2


def test_op_build_similarity_edges_invalid_top_k(tmp_path):
    corpus = tmp_path / "corpus"
    _write_doc(corpus / "a.md", "x y z")
    _write_doc(corpus / "b.md", "x y w")
    skill = PipelineOps()
    out = skill.execute({
        "op": "build_similarity_edges",
        "corpus_dir": str(corpus),
        "graph_db": str(tmp_path / "g.db"),
        "top_k": 0,
    })
    assert out["ok"] is False
    assert "top_k" in out["error"]


def test_op_build_similarity_edges_unknown_op():
    skill = PipelineOps()
    out = skill.execute({"op": "does_not_exist"})
    assert out["ok"] is False
    assert "unknown op" in out["error"]
    assert "build_similarity_edges" in out["error"]


def test_op_build_similarity_edges_empty_corpus_dir(tmp_path):
    """Empty string corpus_dir should be rejected (not silently fall back to production corpus)."""
    skill = PipelineOps()
    out = skill.execute({
        "op": "build_similarity_edges",
        "corpus_dir": "",
        "graph_db": str(tmp_path / "g.db"),
    })
    assert out["ok"] is False
    assert "corpus_dir" in out["error"]


def test_op_build_similarity_edges_invalid_min_score(tmp_path):
    corpus = tmp_path / "corpus"
    _write_doc(corpus / "a.md", "x y z")
    _write_doc(corpus / "b.md", "x y w")
    skill = PipelineOps()
    out = skill.execute({
        "op": "build_similarity_edges",
        "corpus_dir": str(corpus),
        "graph_db": str(tmp_path / "g.db"),
        "min_score": "not-a-number",
    })
    assert out["ok"] is False
    assert "min_score" in out["error"]
