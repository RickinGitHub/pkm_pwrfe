"""Knowledge Server — fast retrieval with metadata filtering.

Ops:
  - lookup <query>    : substring match → BM25 fallback (fast, full docs)
  - filter <tags...>  : filter by tags, return doc list with metadata
  - list              : list all docs with title/tags/date
  - tags              : list all unique tags in corpus

Supports shared CorpusLoader + MetadataIndex.
"""

from pathlib import Path
from rank_bm25 import BM25Okapi

from rag.corpus_loader import CorpusLoader
from rag.metadata import MetadataIndex


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


class KnowledgeServer:
    """MCP knowledge server — lookup, filter, list, tags.

    Args:
        corpus: Path to corpus directory (str) or a shared CorpusLoader instance.
        metadata: Optional shared MetadataIndex (avoids duplicate parsing).
    """

    def __init__(self, corpus: str | CorpusLoader, metadata: MetadataIndex | None = None):
        if isinstance(corpus, CorpusLoader):
            self._loader = corpus
        else:
            self._loader = CorpusLoader(str(corpus))

        if metadata is not None:
            self._meta = metadata
        else:
            self._meta = MetadataIndex(str(self._loader.dir))
            self._meta.build()

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
        """Re-scan corpus and rebuild all indexes. Returns doc count."""
        count = self._loader.reload()
        self._meta.build()
        self._build_index()
        return count

    # ---- MCP protocol ----

    def execute(self, args: dict) -> dict:
        op = args.get("op")
        if op == "lookup":
            return self._do_lookup(args)
        if op == "filter":
            return self._do_filter(args)
        if op == "list":
            return self._do_list(args)
        if op == "tags":
            return self._do_tags(args)
        return {"ok": False, "result": None, "error": f"unknown op: {op}"}

    # ---- ops ----

    def _do_lookup(self, args: dict) -> dict:
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return {"ok": False, "result": None, "error": "missing or empty 'query'"}

        # Optional: pre-filter by tags before text search
        tags = args.get("tags")
        if tags and isinstance(tags, list):
            filtered = self._meta.filter(tags=tags)
            allowed_ids = {m.id for m in filtered}
            candidates = [(did, txt) for did, txt in self._loader.docs if did in allowed_ids]
        else:
            candidates = self._loader.docs

        if not candidates:
            return {"ok": True, "result": "no match", "error": None}

        # 1. substring match
        q_lower = query.lower()
        for _name, text in candidates:
            if q_lower in text.lower():
                return {"ok": True, "result": text, "error": None}

        # 2. BM25 fallback within filtered set
        corpus_tokens = [_tokenize(t) for _, t in candidates]
        bm25 = BM25Okapi(corpus_tokens)
        scores = bm25.get_scores(_tokenize(query))
        best = int(scores.argmax())
        if scores[best] <= 0:
            return {"ok": True, "result": "no match", "error": None}
        return {"ok": True, "result": candidates[best][1], "error": None}

    def _do_filter(self, args: dict) -> dict:
        tags = args.get("tags")
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        if not tags:
            return {"ok": False, "result": None, "error": "missing 'tags' (list or comma-separated)"}

        results = self._meta.filter(
            tags=tags,
            date_from=args.get("date_from"),
            date_to=args.get("date_to"),
            max_results=int(args.get("max_results", 50)),
        )
        return {
            "ok": True,
            "result": {
                "count": len(results),
                "docs": [m.to_dict() for m in results],
            },
            "error": None,
        }

    def _do_list(self, args: dict) -> dict:
        docs = self._meta.docs
        if not docs:
            return {"ok": True, "result": {"count": 0, "docs": []}, "error": None}
        return {
            "ok": True,
            "result": {
                "count": len(docs),
                "docs": [m.to_dict() for m in docs],
            },
            "error": None,
        }

    def _do_tags(self, args: dict) -> dict:
        return {
            "ok": True,
            "result": {
                "count": len(self._meta.all_tags),
                "tags": self._meta.all_tags,
            },
            "error": None,
        }
