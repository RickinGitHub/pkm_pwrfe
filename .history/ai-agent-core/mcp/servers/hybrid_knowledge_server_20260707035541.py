"""Hybrid RAG Knowledge Server — wraps HybridRetriever as MCP tool.

Loads corpus docs into HybridRetriever with a deterministic pseudo-embedder.
Exposes `execute({"op": "lookup", "query": "..."})` returning envelope.
When a real embedding model is configured, replaces the pseudo-embedder.
"""

import hashlib
import os
from pathlib import Path

from rag.retriever import HybridRetriever
from rag.vector_db.store import VectorStore


def _pseudo_embed(text: str, dim: int = 64) -> list[float]:
    """Deterministic pseudo-embedding from text hash (placeholder).

    Splits SHA256 hex into dim chunks, maps each to [-1, 1].
    Replace with a real embedding model (e.g. sentence-transformers) in production.
    """
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    chunk = len(h) // dim
    vec = []
    for i in range(dim):
        segment = h[i * chunk : (i + 1) * chunk]
        val = int(segment, 16) / (16 ** len(segment))  # [0, 1)
        vec.append(val * 2.0 - 1.0)  # [-1, 1]
    return vec


class HybridKnowledgeServer:
    """MCP-compatible server wrapping HybridRetriever for semantic knowledge lookup."""

    def __init__(
        self,
        corpus_dir: str,
        vector_db_path: str | None = None,
        embed_dim: int = 64,
    ):
        self._dir = Path(corpus_dir)
        db_path = vector_db_path or os.path.join(corpus_dir, "..", "hybrid_vector.db")
        self._store = VectorStore(str(db_path), dim=embed_dim)
        self._retriever = HybridRetriever(
            store=self._store,
            embedder=lambda t: _pseudo_embed(t, embed_dim),
        )
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not self._dir.exists():
            self._loaded = True
            return
        for p in sorted(self._dir.rglob("*.txt")):
            if p.is_file():
                self._retriever.add(
                    str(p.relative_to(self._dir)),
                    p.read_text(encoding="utf-8"),
                )
        for p in sorted(self._dir.rglob("*.md")):
            if p.is_file():
                self._retriever.add(
                    str(p.relative_to(self._dir)),
                    p.read_text(encoding="utf-8"),
                )
        self._loaded = True

    def execute(self, args: dict) -> dict:
        op = args.get("op")
        if op != "lookup":
            return {"ok": False, "result": None, "error": f"unknown op: {op}"}
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return {"ok": False, "result": None, "error": "missing or empty 'query'"}
        self._ensure_loaded()
        k = int(args.get("k", 5))
        hits = self._retriever.query(query, k=k)
        if not hits:
            return {"ok": True, "result": "no match", "error": None}
        results = [
            {"id": doc_id, "text": text, "score": round(score, 4)}
            for doc_id, text, score in hits
        ]
        return {"ok": True, "result": {"hits": results, "top_text": hits[0][1]}, "error": None}
