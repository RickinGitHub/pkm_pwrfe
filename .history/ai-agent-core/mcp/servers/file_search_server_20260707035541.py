"""File Search MCP Server — recursive file search by name pattern.

Exposes `execute({"op": "search", "pattern": "*.py", "dir": ".", "max_results": 20})`.
"""

import os
from pathlib import Path


class FileSearchServer:
    """MCP-compatible server for recursive file search by glob pattern."""

    def __init__(self, root_dir: str | None = None):
        self._root = Path(root_dir) if root_dir else Path.cwd()

    def execute(self, args: dict) -> dict:
        op = args.get("op")
        if op != "search":
            return {"ok": False, "result": None, "error": f"unknown op: {op}"}

        pattern = args.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            return {"ok": False, "result": None, "error": "missing or empty 'pattern'"}

        search_dir = Path(args.get("dir", "."))
        if not search_dir.is_absolute():
            search_dir = self._root / search_dir
        if not search_dir.exists():
            return {"ok": False, "result": None, "error": f"directory not found: {search_dir}"}

        max_results = int(args.get("max_results", 20))
        case_sensitive = bool(args.get("case_sensitive", False))

        results = []
        glob_pattern = pattern if case_sensitive else pattern.lower()
        for p in search_dir.rglob("*"):
            if not p.is_file():
                continue
            name = p.name if case_sensitive else p.name.lower()
            if not Path(name).match(glob_pattern):
                continue
            try:
                stat = p.stat()
                results.append({
                    "path": str(p.relative_to(self._root)),
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                })
            except OSError:
                results.append({
                    "path": str(p.relative_to(self._root)),
                    "size": -1,
                    "modified": 0,
                })
            if len(results) >= max_results:
                break

        return {
            "ok": True,
            "result": {
                "pattern": pattern,
                "count": len(results),
                "files": sorted(results, key=lambda x: x["path"]),
            },
            "error": None,
        }
