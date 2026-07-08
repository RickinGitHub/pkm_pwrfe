from collections.abc import Callable
from rank_bm25 import BM25Okapi


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-9:
        return [1.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


class HybridRetriever:
    def __init__(
        self,
        store,
        embedder: Callable[[str], list[float]],
        bm25_k1: float = 1.5,
        bm25_b: float = 0.75,
    ):
        self._store = store
        self._embedder = embedder
        self._k1 = bm25_k1
        self._b = bm25_b
        self._docs: list[tuple[str, str]] = []

    def add(self, id: str, text: str) -> None:
        self._docs.append((id, text))
        self._store.upsert(id, text, self._embedder(text))

    def query(
        self,
        text: str,
        k: int = 5,
        bm25_weight: float = 0.5,
        vector_weight: float = 0.5,
    ) -> list[tuple[str, str, float]]:
        if not self._docs:
            return []
        corpus_tokens = [_tokenize(t) for _, t in self._docs]
        bm25 = BM25Okapi(corpus_tokens, k1=self._k1, b=self._b)
        query_tokens = _tokenize(text)
        bm25_scores = bm25.get_scores(query_tokens).tolist()
        vec_hits = self._store.search(self._embedder(text), k=len(self._docs))
        vec_scores_by_id = {hid: max(0.0, sim) for hid, _, sim in vec_hits}
        vec_raw = [vec_scores_by_id.get(doc_id, 0.0) for doc_id, _ in self._docs]
        bm25_norm = _minmax(bm25_scores)
        vec_norm = _minmax(vec_raw)
        fused = []
        for (doc_id, doc_text), b_score, v_score in zip(self._docs, bm25_norm, vec_norm):
            score = bm25_weight * b_score + vector_weight * v_score
            fused.append((doc_id, doc_text, float(score)))
        fused.sort(key=lambda x: x[2], reverse=True)
        return fused[:k]
