import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS triplets (
    subject   TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object    TEXT NOT NULL,
    ts        REAL NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_subject   ON triplets(subject);
CREATE INDEX IF NOT EXISTS idx_predicate ON triplets(predicate);
"""


class LongTerm:
    def __init__(self, path: str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def add(self, subject: str, predicate: str, obj: str) -> None:
        self._conn.execute(
            "INSERT INTO triplets(subject, predicate, object) VALUES (?, ?, ?)",
            (subject, predicate, obj),
        )
        self._conn.commit()

    def query(
        self,
        subject: str | None = None,
        predicate: str | None = None,
    ) -> list[tuple[str, str, str]]:
        stmt = "SELECT subject, predicate, object FROM triplets WHERE 1=1"
        params: list = []
        if subject is not None:
            stmt += " AND subject = ?"
            params.append(subject)
        if predicate is not None:
            stmt += " AND predicate = ?"
            params.append(predicate)
        stmt += " ORDER BY ts ASC"
        cur = self._conn.execute(stmt, params)
        return [(r[0], r[1], r[2]) for r in cur.fetchall()]

    def summarize_as_text(self) -> str:
        rows = self.query()
        return "\n".join(f"{s} {p} {o}" for s, p, o in rows)

    def close(self) -> None:
        self._conn.close()
