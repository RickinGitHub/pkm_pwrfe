# -*- coding: utf-8 -*-
"""Build BM25 top-k similarity edges into knowledge_edges (P1).

For each document in rag/corpus, compute BM25 scores over the rest of the
corpus and write the top-k most similar docs as edges with
rel_type='bm25_similar'. Grows the knowledge graph from a handful of manual
wikilink edges to a comprehensive similarity network.

Usage:
    python3 scripts/build_similarity_edges.py
    python3 scripts/build_similarity_edges.py --top-k 5 --corpus rag/corpus
    python3 scripts/build_similarity_edges.py --clear  # wipe bm25_similar edges first
"""

import argparse
import os
import sys

# Make project root importable when run as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rank_bm25 import BM25Okapi

from rag.corpus_loader import CorpusLoader
from rag.graph_index import GraphIndex
from rag.tokenizer import tokenize


def _normalize_path(doc_id: str, corpus_dir_abs: str) -> str:
    """Store edges using absolute corpus-relative path so they resolve cross-tool."""
    return os.path.join(corpus_dir_abs, doc_id)


def build_edges(
    corpus_dir: str,
    graph_db_path: str,
    top_k: int = 5,
    clear_existing: bool = False,
    min_score: float = -1.0,
) -> dict:
    """Build BM25 similarity edges and upsert into knowledge_edges.

    Returns a stats dict: {docs, edges_added, edges_updated, skipped_self}.
    """
    loader = CorpusLoader(corpus_dir, chunk=False)
    docs = loader.docs
    if not docs:
        return {"docs": 0, "edges_added": 0, "edges_updated": 0, "skipped_self": 0}

    corpus_dir_abs = os.path.abspath(corpus_dir)
    paths = [_normalize_path(doc_id, corpus_dir_abs) for doc_id, _ in docs]
    tokenized = [tokenize(text) for _, text in docs]

    graph = GraphIndex(graph_db_path)

    if clear_existing:
        graph._conn.execute("DELETE FROM knowledge_edges WHERE rel_type=?", ("bm25_similar",))
        graph._conn.commit()

    bm25 = BM25Okapi(tokenized)

    added = 0
    updated = 0
    skipped_self = 0

    for i in range(len(docs)):
        scores = bm25.get_scores(tokenized[i])
        # Rank others by score desc, exclude self, take top_k.
        ranked = sorted(
            ((j, float(scores[j])) for j in range(len(docs)) if j != i),
            key=lambda x: x[1],
            reverse=True,
        )[:top_k]

        for j, score in ranked:
            if score < min_score:
                continue
            is_new = graph.upsert_edge(
                source_path=paths[i],
                target_path=paths[j],
                weight=score,
                rel_type="bm25_similar",
            )
            if is_new:
                added += 1
            else:
                updated += 1

        skipped_self += 0  # self handled by ranked filter

    return {
        "docs": len(docs),
        "edges_added": added,
        "edges_updated": updated,
        "skipped_self": skipped_self,
        "total_bm25_edges": graph._conn.execute(
            "SELECT COUNT(*) FROM knowledge_edges WHERE rel_type='bm25_similar'"
        ).fetchone()[0],
        "total_edges": graph.edges_count(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build BM25 similarity edges")
    parser.add_argument("--corpus", default=os.environ.get("CORPUS_DIR", "rag/corpus"))
    parser.add_argument("--graph-db", default=os.environ.get("GRAPH_DB_PATH", "rag/graph_index.db"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=-1.0)
    parser.add_argument("--clear", action="store_true", help="Remove existing bm25_similar edges first")
    args = parser.parse_args()

    stats = build_edges(
        corpus_dir=args.corpus,
        graph_db_path=args.graph_db,
        top_k=args.top_k,
        clear_existing=args.clear,
        min_score=args.min_score,
    )
    print("BM25 similarity edges build complete:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
