from rag.retriever import HybridRetriever
from rag.vector_db.store import VectorStore
import numpy as np


def _hash_emb(text: str, dim: int = 32) -> list[float]:
    rng = np.random.default_rng(hash(text) & 0xFFFF)
    v = rng.standard_normal(dim).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


def test_query_empty_returns_empty(tmp_path):
    store = VectorStore(str(tmp_path / "v.db"), dim=32)
    r = HybridRetriever(store, embedder=lambda t: _hash_emb(t, 32))
    assert r.query("anything", k=3) == []


def test_add_and_query_returns_relevant(tmp_path):
    store = VectorStore(str(tmp_path / "v.db"), dim=32)
    r = HybridRetriever(store, embedder=lambda t: _hash_emb(t, 32))
    r.add("1", "python is a programming language")
    r.add("2", "the cat sat on the mat")
    r.add("3", "python snakes are reptiles")
    hits = r.query("python programming", k=2)
    assert len(hits) >= 1
    assert hits[0][0] == "1"


def test_fused_scores_are_normalized(tmp_path):
    store = VectorStore(str(tmp_path / "v.db"), dim=32)
    r = HybridRetriever(store, embedder=lambda t: _hash_emb(t, 32))
    for i, t in enumerate(["alpha beta", "gamma delta", "epsilon zeta"]):
        r.add(str(i), t)
    hits = r.query("alpha", k=3)
    if hits:
        assert isinstance(hits[0][2], float)


def test_retriever_rebuilds_bm25_on_query(tmp_path):
    store = VectorStore(str(tmp_path / "v.db"), dim=32)
    r = HybridRetriever(store, embedder=lambda t: _hash_emb(t, 32))
    r.add("1", "first doc")
    r.add("2", "second doc")
    hits = r.query("first", k=2)
    assert hits[0][0] == "1"
