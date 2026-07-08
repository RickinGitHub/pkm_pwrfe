"""SQLite FTS5 full-text index for knowledge base documents.

Mirrors rag/vector_db/store.py: one class wrapping a sqlite virtual table.
Use alongside vector store — FTS5 for keyword/BM25-ish search, vec0 for
semantic similarity. Both can coexist on the same corpus.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(
    path,
    title,
    category,
    content,
    timestamp,
    tokenize = 'trigram'
);
"""


class FtsIndex:
    """FTS5-backed full-text index over Markdown documents.

    Columns match the spec: path (PK), title, category, content, timestamp.
    Upsert = DELETE + INSERT (FTS5 has no native upsert).
    """

    def __init__(self, path: str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def upsert(
        self,
        path: str,
        title: str,
        category: str,
        content: str,
        timestamp: str | None = None,
    ) -> None:
        ts = timestamp or datetime.now().isoformat()
        self._conn.execute("DELETE FROM docs WHERE path = ?", (path,))
        self._conn.execute(
            "INSERT INTO docs(path, title, category, content, timestamp) VALUES (?, ?, ?, ?, ?)",
            (path, title, category, content, ts),
        )
        self._conn.commit()

    def delete(self, path: str) -> int:
        cur = self._conn.execute("DELETE FROM docs WHERE path = ?", (path,))
        self._conn.commit()
        return cur.rowcount

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        q = query.strip()
        if not q:
            return []
        # trigram tokenizer requires >= 3-char queries for MATCH. Use a
        # raw substring scan via instr() as a fallback for 1-2 char queries
        # (covers 2-char Chinese lookup like "简历").
        if len(q) < 3:
            cur = self._conn.execute(
                "SELECT path, title, category, "
                "substr(content, max(1, instr(content, ?) - 30), 120), "
                "timestamp, 0 FROM docs WHERE instr(content, ?) > 0 "
                "ORDER BY timestamp DESC LIMIT ?",
                (q, q, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT path, title, category, snippet(docs, 3, '<', '>', '...', 12), "
                "timestamp, rank FROM docs WHERE docs MATCH ? ORDER BY rank LIMIT ?",
                (q, limit),
            )
        rows = cur.fetchall()
        return [
            {
                "path": r[0],
                "title": r[1],
                "category": r[2],
                "snippet": r[3],
                "timestamp": r[4],
                "rank": r[5],
            }
            for r in rows
        ]

    def count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM docs")
        return int(cur.fetchone()[0])

    def close(self) -> None:
        self._conn.close()
