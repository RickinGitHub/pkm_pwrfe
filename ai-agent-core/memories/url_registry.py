# -*- coding: utf-8 -*-
"""URL -> local-path registry for fetch deduplication (P0-2).

Prevents re-downloading the same URL on every fetch. Backed by a tiny SQLite DB.
Kept separate from long_term/graph_index so it stays swappable without touching
other stores.
"""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS url_map (
    url        TEXT PRIMARY KEY,
    filepath   TEXT NOT NULL,
    title      TEXT,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_filepath ON url_map(filepath);
"""


class UrlRegistry:
    """SQLite-backed URL→filepath map. Thread-safe via a single connection + lock."""

    def __init__(self, path: str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def lookup(self, url: str) -> Optional[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT url, filepath, title, fetched_at FROM url_map WHERE url=?",
                (url,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {"url": row[0], "filepath": row[1], "title": row[2], "fetched_at": row[3]}

    def record(self, url: str, filepath: str, title: str = "") -> None:
        ts = datetime.now().isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO url_map(url, filepath, title, fetched_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(url) DO UPDATE SET filepath=excluded.filepath, "
                "title=excluded.title, fetched_at=excluded.fetched_at",
                (url, filepath, title, ts),
            )
            self._conn.commit()

    def count(self) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM url_map")
            return int(cur.fetchone()[0])

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM url_map")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
