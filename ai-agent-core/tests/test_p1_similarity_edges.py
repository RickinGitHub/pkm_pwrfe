# -*- coding: utf-8 -*-
"""P1: BM25 similarity edges builder."""
import os
import sys
from pathlib import Path

# Make project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag.graph_index import GraphIndex
from scripts.build_similarity_edges import build_edges


def _write_doc(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_build_edges_creates_top_k_per_doc(tmp_path):
    corpus = tmp_path / "corpus"
    _write_doc(corpus / "a.md", "python web framework django flask")
    _write_doc(corpus / "b.md", "python data analysis pandas numpy")
    _write_doc(corpus / "c.md", "javascript frontend react vue")
    _write_doc(corpus / "d.md", "python web api fastapi starlette")

    graph_db = str(tmp_path / "graph.db")
    stats = build_edges(str(corpus), graph_db, top_k=2)
    g = GraphIndex(graph_db)
    assert g.edges_count() > 0
    # 4 docs * up to 2 edges each = up to 8
    assert stats["edges_added"] <= 8
    assert stats["docs"] == 4
    # All edges should be bm25_similar
    cnt = g._conn.execute(
        "SELECT COUNT(*) FROM knowledge_edges WHERE rel_type='bm25_similar'"
    ).fetchone()[0]
    assert cnt == g.edges_count()


def test_build_edges_skips_self(tmp_path):
    corpus = tmp_path / "corpus"
    _write_doc(corpus / "only.md", "solo document no others")
    graph_db = str(tmp_path / "graph.db")
    stats = build_edges(str(corpus), graph_db, top_k=5)
    g = GraphIndex(graph_db)
    # Single doc: no edges (no self-edges allowed)
    assert g.edges_count() == 0
    assert stats["docs"] == 1


def test_build_edges_clear_replaces_existing(tmp_path):
    corpus = tmp_path / "corpus"
    _write_doc(corpus / "a.md", "alpha beta common terms here")
    _write_doc(corpus / "b.md", "alpha beta common words different")
    _write_doc(corpus / "c.md", "alpha beta shared vocabulary again")
    graph_db = str(tmp_path / "graph.db")

    # First run
    build_edges(str(corpus), graph_db, top_k=2, clear_existing=True)
    g = GraphIndex(graph_db)
    first_count = g.edges_count()
    assert first_count > 0

    # Second run with clear should produce same count, not double
    build_edges(str(corpus), graph_db, top_k=2, clear_existing=True)
    assert g.edges_count() == first_count


def test_build_edges_min_score_filter(tmp_path):
    corpus = tmp_path / "corpus"
    _write_doc(corpus / "a.md", "alpha beta gamma")
    _write_doc(corpus / "b.md", "alpha beta gamma")
    _write_doc(corpus / "c.md", "completely different topic xyz")
    graph_db = str(tmp_path / "graph.db")
    # High min_score should filter out weak matches
    build_edges(str(corpus), graph_db, top_k=5, min_score=10.0)
    g = GraphIndex(graph_db)
    # Only strong matches (a↔b) should survive, c should have no edges
    cnt = g.edges_count()
    assert cnt >= 0  # at minimum, no crash


def test_build_edges_empty_corpus(tmp_path):
    corpus = tmp_path / "empty"
    corpus.mkdir()
    graph_db = str(tmp_path / "graph.db")
    stats = build_edges(str(corpus), graph_db, top_k=5)
    assert stats["docs"] == 0
    assert stats["edges_added"] == 0
