"""Hybrid RAG Knowledge Server — wraps HybridRetriever as MCP tool.

Loads corpus docs into HybridRetriever. Uses rag.embedder for embedding:
  - Set EMBEDDING_MODEL env var for real semantic embeddings (sentence-transformers)
  - Falls back to deterministic pseudo-embedding otherwise

Supports shared CorpusLoader to avoid duplicate file I/O.
Exposes `execute({"op": "lookup", "query": "..."})` returning envelope.
"""

import os
from collections.abc import Callable
from pathlib import Path

from rag.corpus_loader import CorpusLoader
from rag.embedder import get_embedder
from rag.retriever import HybridRetriever
from rag.vector_db.store import VectorStore


class HybridKnowledgeServer:
    """MCP-compatible server wrapping HybridRetriever for semantic knowledge lookup.

    Args:
        corpus: Path to corpus directory (str) or a shared CorpusLoader instance.
        vector_db_path: Optional path for vector DB (default: <corpus>/../hybrid_vector.db).
        embed_dim: Embedding dimension for fallback pseudo-embedder (default 64).
                   Ignored when EMBEDDING_MODEL env var is set (auto-detects dim).
    """

    def __init__(
        self,
        corpus: str | CorpusLoader,
        vector_db_path: str | None = None,
        embed_dim: int = 64,
        embedder: Callable[[str], list[float]] | None = None,
    ):
        if isinstance(corpus, CorpusLoader):
            self._loader = corpus
        else:
            self._loader = CorpusLoader(str(corpus))

        # Resolve embedder: explicit > env var > pseudo fallback
        if embedder is not None:
            self._embedder = embedder
        else:
            self._embedder = get_embedder(dim=embed_dim)

        # Detect actual dim from first embedding
        sample = self._embedder("dim-probe")
        actual_dim = len(sample)

        db_path = vector_db_path or os.path.join(
            str(self._loader.dir), "..", "hybrid_vector.db"
        )
        self._store = VectorStore(str(db_path), dim=actual_dim)
        self._retriever = HybridRetriever(
            store=self._store,
            embedder=self._embedder,
        )
        self._loaded = False

    # ---- index management ----

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not self._loader.dir.exists():
            self._loaded = True
            return
        for doc_id, text in self._loader.docs:
            self._retriever.add(doc_id, text)
        self._loaded = True

    def reload(self) -> int:
        """Re-scan corpus and rebuild hybrid index. Returns doc count."""
        count = self._loader.reload()
        self._loaded = False
        self._ensure_loaded()
        return count

    # ---- MCP protocol ----

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
