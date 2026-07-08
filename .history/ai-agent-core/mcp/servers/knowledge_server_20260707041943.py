from pathlib import Path
from rank_bm25 import BM25Okapi

from rag.corpus_loader import CorpusLoader


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


class KnowledgeServer:
    """MCP knowledge lookup server — substring match with BM25 fallback.

    Supports shared CorpusLoader to avoid duplicate file I/O when multiple
    servers use the same corpus.

    Args:
        corpus: Path to corpus directory (str) or a shared CorpusLoader instance.
    """

    def __init__(self, corpus: str | CorpusLoader):
        if isinstance(corpus, CorpusLoader):
            self._loader = corpus
        else:
            self._loader = CorpusLoader(str(corpus))
        self._bm25: BM25Okapi | None = None
        self._build_index()

    # ---- index management ----

    def _build_index(self) -> None:
        docs = self._loader.docs
        if not docs:
            self._bm25 = None
            return
        corpus_tokens = [_tokenize(t) for _, t in docs]
        self._bm25 = BM25Okapi(corpus_tokens)

    def reload(self) -> int:
        """Re-scan corpus and rebuild BM25 index. Returns doc count."""
        count = self._loader.reload()
        self._build_index()
        return count

    # ---- MCP protocol ----

    def execute(self, args: dict) -> dict:
        op = args.get("op")
        if op != "lookup":
            return {"ok": False, "result": None, "error": f"unknown op: {op}"}
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return {"ok": False, "result": None, "error": "missing or empty 'query'"}

        docs = self._loader.docs

        # 1. substring match (fast path)
        q_lower = query.lower()
        for _name, text in docs:
            if q_lower in text.lower():
                return {"ok": True, "result": text, "error": None}

        # 2. BM25 fallback (cached index)
        if not docs:
            return {"ok": True, "result": "", "error": None}
        if self._bm25 is None:
            self._build_index()
        if self._bm25 is None:
            return {"ok": True, "result": "", "error": None}

        scores = self._bm25.get_scores(_tokenize(query))
        best = int(scores.argmax())
        if scores[best] <= 0:
            return {"ok": True, "result": "no match", "error": None}
        return {"ok": True, "result": docs[best][1], "error": None}
