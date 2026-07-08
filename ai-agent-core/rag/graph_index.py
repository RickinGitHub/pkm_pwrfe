"""SQLite-backed document graph + knowledge edges — L1/L2/L3/L4 + multi-category + bidirectional links.

Phase 2: SQLite WAL document_graph 替代 config/index.yaml。
Phase 4: 多标签交叉（Multi-homing）+ knowledge_edges 关系图谱。

Schema:
    CREATE TABLE document_graph (
        path TEXT, l1 TEXT, l2 TEXT, l3 TEXT,
        added_at TEXT, level TEXT DEFAULT 'L4',
        PRIMARY KEY (path, l1, l2, l3)   -- Phase 4 复合主键，允许同 path 多标签
    );

    CREATE TABLE knowledge_edges (
        source_path TEXT, target_path TEXT,
        weight REAL, rel_type TEXT, added_at TEXT,
        PRIMARY KEY (source_path, target_path)
    );
"""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


# 模块级迁移单例锁：同一 db path 只迁移一次，其他线程等待
_migration_done: set[str] = set()
_migration_lock = threading.Lock()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS document_graph (
    path     TEXT NOT NULL,
    l1       TEXT NOT NULL,
    l2       TEXT NOT NULL,
    l3       TEXT NOT NULL,
    added_at TEXT NOT NULL,
    level    TEXT NOT NULL DEFAULT 'L4',
    PRIMARY KEY (path, l1, l2, l3)
);
CREATE INDEX IF NOT EXISTS idx_l1l2l3 ON document_graph(l1, l2, l3);
CREATE INDEX IF NOT EXISTS idx_path ON document_graph(path);

CREATE TABLE IF NOT EXISTS knowledge_edges (
    source_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    weight      REAL NOT NULL DEFAULT 1.0,
    rel_type    TEXT NOT NULL DEFAULT 'related',
    added_at    TEXT NOT NULL,
    PRIMARY KEY (source_path, target_path)
);
CREATE INDEX IF NOT EXISTS idx_edge_source ON knowledge_edges(source_path);
CREATE INDEX IF NOT EXISTS idx_edge_target ON knowledge_edges(target_path);

-- Phase 7: L5 chunk-level atomic index
CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id    TEXT NOT NULL,
    parent_path TEXT NOT NULL,
    chunk_text  TEXT NOT NULL,
    l1          TEXT NOT NULL,
    l2          TEXT NOT NULL,
    l3          TEXT NOT NULL,
    added_at    TEXT NOT NULL,
    level       TEXT NOT NULL DEFAULT 'L5',
    PRIMARY KEY (chunk_id)
);
CREATE INDEX IF NOT EXISTS idx_chunk_parent ON document_chunks(parent_path);
CREATE INDEX IF NOT EXISTS idx_chunk_l1l2l3 ON document_chunks(l1, l2, l3);
"""


class GraphIndex:
    """SQLite-backed L1/L2/L3/L4 document graph + knowledge_edges.

    Phase 2: SQLite WAL document_graph，替代 YAML 全局锁。
    Phase 4: Multi-homing（同 path 多标签）+ knowledge_edges 关系图谱。
    """

    def __init__(self, path: str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._ensure_migrated()
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---- migration ----

    def _ensure_migrated(self) -> None:
        """模块级单例锁 + 一次性迁移：避免多线程并发 _migrate 撞名。

        策略：
        1. 全局锁内检查 `_migration_done` set，已迁移则直接返回
        2. 否则进入 `_migrate_inner`，用 `BEGIN IMMEDIATE` 锁数据库
        3. 迁移完成后加入 `_migration_done`，其他线程拿锁后看到 done 直接返回
        """
        global _migration_done
        db_key = str(self._path.resolve())
        with _migration_lock:
            if db_key in _migration_done:
                return
            self._migrate_inner()
            _migration_done.add(db_key)

    def _migrate_inner(self) -> None:
        """Migrate from Phase 2 schema (path PRIMARY KEY) to Phase 4 (composite PK)."""
        cur = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='document_graph'"
        )
        if cur.fetchone() is None:
            return  # 全新库，由 _SCHEMA 负责建表
        cols = self._conn.execute("PRAGMA table_info(document_graph)").fetchall()
        pk_cols = [c[1] for c in cols if c[5] == 1]
        if len(pk_cols) >= 2:
            return  # 已是复合主键，无需迁移

        # 用 BEGIN IMMEDIATE 锁住数据库
        try:
            self._conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            # 极端情况：其他进程持锁超时——直接返回，_SCHEMA 会建表（但可能丢旧数据）
            return

        try:
            # 再检查一次
            cur = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='document_graph'"
            )
            if cur.fetchone() is None:
                return
            cols = self._conn.execute("PRAGMA table_info(document_graph)").fetchall()
            pk_cols = [c[1] for c in cols if c[5] == 1]
            if len(pk_cols) >= 2:
                return

            # 生成唯一备份表名
            import time, random
            ts_parts = [
                datetime.now().strftime("%Y%m%d_%H%M%S"),
                f"{int(time.time()*1000) % 1000:03d}",
                f"{random.randint(0,9999):04d}",
            ]
            bak = f"document_graph_bak_{'_'.join(ts_parts)}"
            self._conn.execute(f"ALTER TABLE document_graph RENAME TO {bak}")
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                f"INSERT OR IGNORE INTO document_graph(path, l1, l2, l3, added_at, level) "
                f"SELECT path, l1, l2, l3, added_at, level FROM {bak}"
            )
        finally:
            try:
                self._conn.execute("COMMIT")
            except sqlite3.OperationalError:
                pass

    # ---- L4 leaf upsert (multi-homing) ----

    def upsert(
        self,
        path: str,
        l1: str,
        l2: str,
        l3: str,
        added_at: str | None = None,
        level: str = "L4",
    ) -> bool:
        """Insert a doc's L4 leaf. Returns True if new row inserted.

        Phase 4: Multi-homing 允许同 path 多次调用 upsert 写入不同 (l1,l2,l3)。
        相同 (path, l1, l2, l3) 幂等（INSERT OR IGNORE）。
        """
        ts = added_at or datetime.now().isoformat()
        cur = self._conn.execute(
            "SELECT 1 FROM document_graph WHERE path=? AND l1=? AND l2=? AND l3=?",
            (path, l1, l2, l3),
        )
        existed = cur.fetchone() is not None
        if existed:
            return False
        self._conn.execute(
            "INSERT OR IGNORE INTO document_graph(path, l1, l2, l3, added_at, level) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (path, l1, l2, l3, ts, level),
        )
        self._conn.commit()
        return True

    def upsert_categories(
        self,
        path: str,
        categories: list[tuple[str, str, str]],
        added_at: str | None = None,
    ) -> list[bool]:
        """Multi-homing: 一次写入多个 (l1, l2, l3) 标签。"""
        return [self.upsert(path, l1, l2, l3, added_at) for l1, l2, l3 in categories]

    def replace_categories(
        self,
        path: str,
        categories: list[tuple[str, str, str]],
        added_at: str | None = None,
    ) -> int:
        """替换文档的所有分类标签（删旧插新）。Returns new rows count."""
        self.delete_path(path)
        n = 0
        for l1, l2, l3 in categories:
            if self.upsert(path, l1, l2, l3, added_at):
                n += 1
        return n

    def delete_path(self, path: str) -> int:
        """Remove ALL rows for a path (multi-homing 时可能多行). Returns rows deleted."""
        cur = self._conn.execute(
            "DELETE FROM document_graph WHERE path = ?", (path,),
        )
        # 同步清理 knowledge_edges 中以该 path 为端点的边
        self._conn.execute(
            "DELETE FROM knowledge_edges WHERE source_path = ? OR target_path = ?",
            (path, path),
        )
        # Phase 7: 同步清理 document_chunks
        self._conn.execute(
            "DELETE FROM document_chunks WHERE parent_path = ?", (path,),
        )
        self._conn.commit()
        return cur.rowcount

    def delete(self, path: str) -> int:
        """Alias for delete_path (backward-compat with Phase 2/3)."""
        return self.delete_path(path)

    def exists(self, path: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM document_graph WHERE path = ? LIMIT 1", (path,),
        )
        return cur.fetchone() is not None

    def get_categories(self, path: str) -> list[dict[str, Any]]:
        """Return all (l1, l2, l3) tags for a path (Multi-homing)."""
        cur = self._conn.execute(
            "SELECT l1, l2, l3, added_at, level FROM document_graph WHERE path = ? "
            "ORDER BY added_at ASC",
            (path,),
        )
        return [
            {"l1": r[0], "l2": r[1], "l3": r[2], "added_at": r[3], "level": r[4]}
            for r in cur.fetchall()
        ]

    def get(self, path: str) -> dict[str, Any] | None:
        """Backward-compat: return first category as flat dict (Phase 2 API)."""
        cats = self.get_categories(path)
        if not cats:
            return None
        c = cats[0]
        return {
            "path": path,
            "l1": c["l1"], "l2": c["l2"], "l3": c["l3"],
            "added_at": c["added_at"], "level": c["level"],
        }

    def filter(
        self,
        l1: str | None = None,
        l2: str | None = None,
        l3: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Filter docs by L1/L2/L3 (AND-ed). Multi-homing: same path may appear
        multiple times if it has multiple matching categories."""
        stmt = "SELECT path, l1, l2, l3, added_at, level FROM document_graph WHERE 1=1"
        params: list[Any] = []
        if l1 is not None:
            stmt += " AND l1 = ?"
            params.append(l1)
        if l2 is not None:
            stmt += " AND l2 = ?"
            params.append(l2)
        if l3 is not None:
            stmt += " AND l3 = ?"
            params.append(l3)
        stmt += " ORDER BY added_at ASC LIMIT ?"
        params.append(limit)
        cur = self._conn.execute(stmt, params)
        return [
            {"path": r[0], "l1": r[1], "l2": r[2], "l3": r[3],
             "added_at": r[4], "level": r[5]}
            for r in cur.fetchall()
        ]

    def list_paths(self, l1: str | None = None, l2: str | None = None,
                   l3: str | None = None) -> list[str]:
        """Return distinct paths matching the L1/L2/L3 filter."""
        stmt = "SELECT DISTINCT path FROM document_graph WHERE 1=1"
        params: list[Any] = []
        if l1 is not None:
            stmt += " AND l1 = ?"
            params.append(l1)
        if l2 is not None:
            stmt += " AND l2 = ?"
            params.append(l2)
        if l3 is not None:
            stmt += " AND l3 = ?"
            params.append(l3)
        cur = self._conn.execute(stmt, params)
        return [r[0] for r in cur.fetchall()]

    def count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM document_graph")
        return int(cur.fetchone()[0])

    def count_distinct_paths(self) -> int:
        cur = self._conn.execute("SELECT COUNT(DISTINCT path) FROM document_graph")
        return int(cur.fetchone()[0])

    def tree(self) -> dict[str, Any]:
        """Build nested tree dict (compatible with old index.yaml structure).

        Multi-homing: 同一 path 可能在多个 (l1,l2,l3) 叶子下出现。
        """
        cur = self._conn.execute(
            "SELECT path, l1, l2, l3, added_at, level FROM document_graph "
            "ORDER BY l1, l2, l3, added_at ASC"
        )
        tree: dict[str, Any] = {}
        for path, l1, l2, l3, added_at, level in cur.fetchall():
            tree.setdefault(l1, {}).setdefault(l2, {}).setdefault(l3, []).append({
                "path": path,
                "added_at": added_at,
                "level": level,
            })
        return tree

    def export_yaml_dict(self) -> dict[str, Any]:
        return {"version": 1, "tree": self.tree()}

    # ---- knowledge_edges (Phase 4) ----

    def upsert_edge(
        self,
        source_path: str,
        target_path: str,
        weight: float = 1.0,
        rel_type: str = "related",
        added_at: str | None = None,
    ) -> bool:
        """Insert or update an edge between two docs. Returns True if new edge."""
        if source_path == target_path:
            return False
        ts = added_at or datetime.now().isoformat()
        cur = self._conn.execute(
            "SELECT 1 FROM knowledge_edges WHERE source_path=? AND target_path=?",
            (source_path, target_path),
        )
        existed = cur.fetchone() is not None
        if existed:
            self._conn.execute(
                "UPDATE knowledge_edges SET weight=?, rel_type=?, added_at=? "
                "WHERE source_path=? AND target_path=?",
                (weight, rel_type, ts, source_path, target_path),
            )
            self._conn.commit()
            return False
        self._conn.execute(
            "INSERT INTO knowledge_edges(source_path, target_path, weight, rel_type, added_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (source_path, target_path, weight, rel_type, ts),
        )
        self._conn.commit()
        return True

    def delete_edge(self, source_path: str, target_path: str) -> int:
        cur = self._conn.execute(
            "DELETE FROM knowledge_edges WHERE source_path=? AND target_path=?",
            (source_path, target_path),
        )
        self._conn.commit()
        return cur.rowcount

    def neighbors(
        self,
        path: str,
        direction: str = "both",
        rel_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return neighbor docs of `path`.

        direction: 'out' (path as source), 'in' (path as target), 'both'.
        rel_type: optional filter by relationship type.
        """
        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        if direction in ("out", "both"):
            stmt = ("SELECT target_path AS neighbor, weight, rel_type, added_at "
                    "FROM knowledge_edges WHERE source_path = ?")
            params: list[Any] = [path]
            if rel_type is not None:
                stmt += " AND rel_type = ?"
                params.append(rel_type)
            stmt += " LIMIT ?"
            params.append(limit)
            for r in self._conn.execute(stmt, params).fetchall():
                if r[0] not in seen:
                    results.append({
                        "path": r[0], "weight": r[1], "rel_type": r[2], "added_at": r[3],
                        "direction": "out",
                    })
                    seen.add(r[0])

        if direction in ("in", "both"):
            stmt = ("SELECT source_path AS neighbor, weight, rel_type, added_at "
                    "FROM knowledge_edges WHERE target_path = ?")
            params = [path]
            if rel_type is not None:
                stmt += " AND rel_type = ?"
                params.append(rel_type)
            stmt += " LIMIT ?"
            params.append(limit)
            for r in self._conn.execute(stmt, params).fetchall():
                if r[0] not in seen:
                    results.append({
                        "path": r[0], "weight": r[1], "rel_type": r[2], "added_at": r[3],
                        "direction": "in",
                    })
                    seen.add(r[0])

        return results[:limit]

    def edges_count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM knowledge_edges")
        return int(cur.fetchone()[0])

    def all_edges(self, limit: int = 1000) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT source_path, target_path, weight, rel_type, added_at "
            "FROM knowledge_edges ORDER BY added_at ASC LIMIT ?",
            (limit,),
        )
        return [
            {"source_path": r[0], "target_path": r[1], "weight": r[2],
             "rel_type": r[3], "added_at": r[4]}
            for r in cur.fetchall()
        ]

    # ---- document_chunks (Phase 7 L5) ----

    def upsert_chunks(
        self,
        parent_path: str,
        l1: str,
        l2: str,
        l3: str,
        chunks: list[tuple[str, str]],
    ) -> int:
        """Phase 7: Upsert L5 chunks for a parent document.

        Args:
            parent_path: absolute path of the parent .md file.
            l1, l2, l3: inherited category from parent.
            chunks: list of (chunk_id, chunk_text) tuples.

        Returns: number of chunks inserted (new rows; existing chunk_ids are
        replaced via INSERT OR REPLACE).
        """
        if not chunks:
            return 0
        ts = datetime.now().isoformat()
        rows = [(cid, parent_path, ctxt, l1, l2, l3, ts, "L5") for cid, ctxt in chunks]
        self._conn.executemany(
            "INSERT OR REPLACE INTO document_chunks"
            "(chunk_id, parent_path, chunk_text, l1, l2, l3, added_at, level) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def delete_chunks(self, parent_path: str) -> int:
        """Phase 7: Delete all chunks for a parent document. Returns rows deleted."""
        cur = self._conn.execute(
            "DELETE FROM document_chunks WHERE parent_path = ?", (parent_path,),
        )
        self._conn.commit()
        return cur.rowcount

    def count_chunks(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM document_chunks")
        return int(cur.fetchone()[0])

    def get_chunks(self, parent_path: str, limit: int = 1000) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT chunk_id, parent_path, chunk_text, l1, l2, l3, added_at, level "
            "FROM document_chunks WHERE parent_path = ? ORDER BY chunk_id ASC LIMIT ?",
            (parent_path, limit),
        )
        return [
            {"chunk_id": r[0], "parent_path": r[1], "chunk_text": r[2],
             "l1": r[3], "l2": r[4], "l3": r[5], "added_at": r[6], "level": r[7]}
            for r in cur.fetchall()
        ]

    def close(self) -> None:
        self._conn.close()
