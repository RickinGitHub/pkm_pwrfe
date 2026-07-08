import hashlib
import json
import math
import re
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path


_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key         TEXT PRIMARY KEY,
    query       TEXT NOT NULL,
    result_json TEXT NOT NULL,
    embedding   BLOB,
    ts          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ts ON cache(ts);
"""


def _normalize(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def _hash(query: str) -> str:
    return hashlib.sha256(_normalize(query).encode("utf-8")).hexdigest()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a < 1e-12 or norm_b < 1e-12:
        return 0.0
    return dot / (norm_a * norm_b)


def _serialize_embedding(vec: list[float]) -> bytes:
    import struct
    return struct.pack(f"{len(vec)}f", *vec)


def _deserialize_embedding(data: bytes) -> list[float]:
    import struct
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))


class CacheGuard:
    def __init__(
        self,
        path: str,
        ttl_seconds: int = 3600,
        embedder: Callable[[str], list[float]] | None = None,
        semantic_threshold: float = 0.85,
    ):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl_seconds
        self._embedder = embedder
        self._semantic_threshold = semantic_threshold
        self._conn = sqlite3.connect(str(self._path))
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._migrate()

    def get(self, query: str) -> dict | None:
        key = _hash(query)
        cur = self._conn.execute(
            "SELECT result_json, ts FROM cache WHERE key = ?",
            (key,),
        )
        row = cur.fetchone()
        if row is None:
            return self._semantic_get(query)
        result_json, ts = row
        if (time.time() - ts) > self._ttl:
            return self._semantic_get(query)
        return json.loads(result_json)

    def _semantic_get(self, query: str) -> dict | None:
        if self._embedder is None:
            return None
        query_emb = self._embedder(query)
        cur = self._conn.execute(
            "SELECT result_json, embedding, ts FROM cache WHERE embedding IS NOT NULL"
        )
        best_score = -1.0
        best_result: dict | None = None
        for result_json, emb_data, ts in cur.fetchall():
            if (time.time() - ts) > self._ttl:
                continue
            cached_emb = _deserialize_embedding(emb_data)
            score = _cosine_similarity(query_emb, cached_emb)
            if score > best_score:
                best_score = score
                best_result = json.loads(result_json)
        if best_score >= self._semantic_threshold and best_result is not None:
            return best_result
        return None

    def set(self, query: str, result: dict) -> None:
        key = _hash(query)
        emb_blob = None
        if self._embedder is not None:
            emb_blob = _serialize_embedding(self._embedder(query))
        self._conn.execute(
            "INSERT OR REPLACE INTO cache(key, query, result_json, embedding, ts) VALUES (?, ?, ?, ?, ?)",
            (key, _normalize(query), json.dumps(result, ensure_ascii=False), emb_blob, int(time.time())),
        )
        self._conn.commit()

    def clear(self) -> None:
        self._conn.execute("DELETE FROM cache")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _migrate(self) -> None:
        """Add embedding column if missing (backward-compatible migration)."""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(cache)").fetchall()}
        if "embedding" not in cols:
            self._conn.execute("ALTER TABLE cache ADD COLUMN embedding BLOB")
            self._conn.commit()
