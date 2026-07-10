"""Knowledge Server — fast retrieval with metadata filtering.

Ops:
  - lookup <query>    : FTS5 全文检索（trigram） → BM25 兜底
  - filter <tags...>  : filter by tags, return doc list with metadata
  - list              : list all docs with title/tags/date
  - tags              : list all unique tags in corpus
  - chunks <path>     : Phase 7 — return L5 chunks of a doc (by path)
  - chunks_by_cat l1 l2 l3 : Phase 7 — return chunks filtered by category

Supports shared CorpusLoader + MetadataIndex.
Supports Chinese natural language queries via bigram tokenization.

FTS5 集成：构造时传入 FtsIndex 实例即可启用。lookup 优先走 FTS5（O(log n)），
无命中时回退到内存 BM25。两者并存，不互斥。

Phase 7: chunks op 需传入 graph_db_path 才能查询 document_chunks 表。
"""

from pathlib import Path
from rank_bm25 import BM25Okapi

from rag.corpus_loader import CorpusLoader
from rag.fts_index import FtsIndex
from rag.graph_index import GraphIndex
from rag.metadata import MetadataIndex
from rag.tokenizer import tokenize as _tokenize


class KnowledgeServer:
    """MCP knowledge server — lookup, filter, list, tags, chunks.

    Args:
        corpus: Path to corpus directory (str) or a shared CorpusLoader instance.
        metadata: Optional shared MetadataIndex (avoids duplicate parsing).
        fts_index: Optional FtsIndex for FTS5 full-text search. When provided,
                   lookup() queries FTS5 first (O(log n)) and falls back to
                   BM25 only when FTS5 returns no hits.
        graph_db_path: Optional path to graph_index.db for Phase 7 chunks op.
                       When provided, enables `chunks <path>` and
                       `chunks_by_cat l1 l2 l3` ops.
    """

    def __init__(
        self,
        corpus: str | CorpusLoader,
        metadata: MetadataIndex | None = None,
        fts_index: FtsIndex | None = None,
        graph_db_path: str | None = None,
    ):
        if isinstance(corpus, CorpusLoader):
            self._loader = corpus
        else:
            self._loader = CorpusLoader(str(corpus))

        if metadata is not None:
            self._meta = metadata
        else:
            self._meta = MetadataIndex(str(self._loader.dir))
            self._meta.build()

        self._fts = fts_index
        self._graph_db_path = graph_db_path
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
        if op == "chunks":
            return self._do_chunks_by_path(args)
        if op == "chunks_by_cat":
            return self._do_chunks_by_category(args)
        if op == "reload":
            return self._do_reload(args)
        return {"ok": False, "result": None, "error": f"unknown op: {op}"}

    # ---- ops ----

    def _do_lookup(self, args: dict) -> dict:
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return {"ok": False, "result": None, "error": "missing or empty 'query'"}

        # Optional: pre-filter by tags before text search
        tags = args.get("tags")
        filtered_ids: set[str] | None = None
        if tags and isinstance(tags, list):
            filtered = self._meta.filter(tags=tags)
            filtered_ids = {m.doc_id for m in filtered}
            candidates = [(did, txt) for did, txt in self._loader.docs if did in filtered_ids]
        else:
            candidates = self._loader.docs

        if not candidates:
            return {"ok": True, "result": "no match", "error": None}

        # 1. FTS5 优先（若已注入 FtsIndex）— O(log n)，支持 snippet 高亮
        if self._fts is not None:
            fts_hits = self._fts.search(query, limit=5)
            for hit in fts_hits:
                # FTS5 path 是绝对路径；CorpusLoader doc_id 是相对路径
                # 用 basename + 文件存在性双重校验
                hit_path = hit.get("path", "")
                if filtered_ids is not None:
                    # tag 过滤启用：校验命中文件在过滤集内
                    try:
                        rel = str(Path(hit_path).relative_to(self._loader.dir))
                    except ValueError:
                        rel = hit_path
                    if rel not in filtered_ids:
                        continue
                return {"ok": True, "result": hit.get("snippet") or hit.get("title") or "", "error": None}

        # 2. 子串匹配（保留原行为，FTS5 不可用或未命中时）
        q_lower = query.lower()
        for _name, text in candidates:
            if q_lower in text.lower():
                return {"ok": True, "result": text, "error": None}

        # 3. BM25 fallback within filtered set
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

    def _do_reload(self, args: dict) -> dict:
        """Re-scan corpus and rebuild all indexes (BM25 + metadata)."""
        count = self.reload()
        return {
            "ok": True,
            "result": {
                "docs_reloaded": count,
                "message": "corpus reloaded, BM25 + metadata indexes rebuilt",
            },
            "error": None,
        }

    # ---- Phase 7: chunks ops ----

    def _do_chunks_by_path(self, args: dict) -> dict:
        """Return L5 chunks of a doc by path. args: {path, limit?}"""
        if not self._graph_db_path:
            return {"ok": False, "result": None,
                    "error": "graph_db_path not configured; cannot query chunks"}
        path = args.get("path")
        if not isinstance(path, str) or not path.strip():
            return {"ok": False, "result": None, "error": "missing or empty 'path'"}
        limit = int(args.get("limit", 1000))
        try:
            gi = GraphIndex(self._graph_db_path)
            try:
                chunks = gi.get_chunks(path, limit=limit)
                count = gi.count_chunks()
            finally:
                gi.close()
        except Exception as e:
            return {"ok": False, "result": None,
                    "error": f"graph_index query failed: {type(e).__name__}: {e}"}
        return {
            "ok": True,
            "result": {
                "path": path,
                "count": len(chunks),
                "total_chunks_in_db": count,
                "chunks": chunks,
            },
            "error": None,
        }

    def _do_chunks_by_category(self, args: dict) -> dict:
        """Return L5 chunks filtered by l1/l2/l3. args: {l1, l2?, l3?, limit?}"""
        if not self._graph_db_path:
            return {"ok": False, "result": None,
                    "error": "graph_db_path not configured; cannot query chunks"}
        l1 = args.get("l1")
        if not l1:
            return {"ok": False, "result": None, "error": "missing 'l1' (required)"}
        l2 = args.get("l2")
        l3 = args.get("l3")
        limit = int(args.get("limit", 1000))
        try:
            gi = GraphIndex(self._graph_db_path)
            try:
                # GraphIndex has no direct chunks-by-category query; filter via SQL
                stmt = ("SELECT chunk_id, parent_path, chunk_text, l1, l2, l3, added_at, level "
                        "FROM document_chunks WHERE l1 = ?")
                params: list = [l1]
                if l2:
                    stmt += " AND l2 = ?"
                    params.append(l2)
                if l3:
                    stmt += " AND l3 = ?"
                    params.append(l3)
                stmt += " ORDER BY chunk_id ASC LIMIT ?"
                params.append(limit)
                rows = gi._conn.execute(stmt, params).fetchall()
                chunks = [
                    {"chunk_id": r[0], "parent_path": r[1], "chunk_text": r[2],
                     "l1": r[3], "l2": r[4], "l3": r[5], "added_at": r[6], "level": r[7]}
                    for r in rows
                ]
            finally:
                gi.close()
        except Exception as e:
            return {"ok": False, "result": None,
                    "error": f"graph_index query failed: {type(e).__name__}: {e}"}
        return {
            "ok": True,
            "result": {
                "l1": l1, "l2": l2, "l3": l3,
                "count": len(chunks),
                "chunks": chunks,
            },
            "error": None,
        }
