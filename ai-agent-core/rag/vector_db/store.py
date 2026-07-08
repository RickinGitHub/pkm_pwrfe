import sqlite3
import sqlite_vec
from pathlib import Path
import numpy as np


_SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id   TEXT PRIMARY KEY,
    text TEXT NOT NULL
);
"""

_VEC_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS vec_docs USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[%(dim)d]
);
"""


def _to_blob(vec: list[float]) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


class VectorStore:
    def __init__(self, path: str, dim: int = 64):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._dim = dim
        self._conn = sqlite3.connect(str(self._path))
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._conn.executescript(_SCHEMA)
        self._conn.executescript(_VEC_SCHEMA % {"dim": dim})
        self._conn.commit()

    def upsert(self, id: str, text: str, embedding: list[float]) -> None:
        if len(embedding) != self._dim:
            raise ValueError(f"embedding dim {len(embedding)} != store dim {self._dim}")
        self._conn.execute(
            "INSERT OR REPLACE INTO docs(id, text) VALUES (?, ?)",
            (id, text),
        )
        self._conn.execute("DELETE FROM vec_docs WHERE id = ?", (id,))
        self._conn.execute(
            "INSERT INTO vec_docs(id, embedding) VALUES (?, ?)",
            (id, _to_blob(embedding)),
        )
        self._conn.commit()

    def search(self, query_emb: list[float], k: int = 5) -> list[tuple[str, str, float]]:
        if len(query_emb) != self._dim:
            raise ValueError(f"query dim {len(query_emb)} != store dim {self._dim}")
        rows = self._conn.execute(
            """
            SELECT v.id, d.text, v.distance
            FROM vec_docs v
            JOIN docs d ON d.id = v.id
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            (_to_blob(query_emb), k),
        ).fetchall()
        return [(r[0], r[1], 1.0 - float(r[2]) if r[2] is not None else 1.0) for r in rows]

    def close(self) -> None:
        self._conn.close()
