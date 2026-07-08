import numpy as np
from rag.vector_db.store import VectorStore


def _rand_unit(seed: int, dim: int = 64) -> list[float]:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


def test_upsert_and_search_returns_self_first(tmp_path):
    store = VectorStore(str(tmp_path / "v.db"), dim=64)
    store.upsert("a", "alpha doc", _rand_unit(1))
    store.upsert("b", "beta doc", _rand_unit(2))
    hits = store.search(_rand_unit(1), k=2)
    assert len(hits) == 2
    assert hits[0][0] == "a"
    assert hits[0][1] == "alpha doc"


def test_search_empty_store_returns_empty(tmp_path):
    store = VectorStore(str(tmp_path / "v.db"), dim=64)
    assert store.search(_rand_unit(1), k=5) == []


def test_upsert_replaces_existing_id(tmp_path):
    store = VectorStore(str(tmp_path / "v.db"), dim=64)
    store.upsert("a", "first", _rand_unit(1))
    store.upsert("a", "second", _rand_unit(1))
    hits = store.search(_rand_unit(1), k=1)
    assert hits[0][1] == "second"


def test_search_returns_scores_in_descending_order(tmp_path):
    store = VectorStore(str(tmp_path / "v.db"), dim=64)
    for i in range(5):
        store.upsert(f"id{i}", f"doc{i}", _rand_unit(i))
    hits = store.search(_rand_unit(0), k=5)
    scores = [h[2] for h in hits]
    assert scores == sorted(scores, reverse=True)
