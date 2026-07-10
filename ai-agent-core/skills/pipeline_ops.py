# -*- coding: utf-8 -*-
"""Linux 管道风格的 Skill 组合器。

将 find_ops、grep_ops 等 Skill 按 Unix 管道语义串联执行。
所有操作返回 ai-agent-core 标准信封：
    {"ok": True,  "result": <list[dict]|int|list[str]>, "error": None}
    {"ok": False, "result": None, "error": "<msg>"}

------------------------------------------------------------------------------
Usage (Skill 接入)
------------------------------------------------------------------------------

    from skills.pipeline_ops import PipelineOps
    skill = PipelineOps()

    # [1] find + grep: 查找所有 .py 文件，在其中搜索 "TODO"
    #    等价于: find . -name "*.py" | xargs grep -n "TODO"
    out = skill.execute({
        "op": "find_grep",
        "path": "/home/user/project",
        "find_name": "*.py",
        "find_recursive": True,
        "grep_pattern": "TODO",
        "grep_line_number": True,
    })

    # [2] find + grep 忽略大小写 + 仅计数
    #    等价于: find src -name "*.py" | xargs grep -i -c "import"
    out = skill.execute({
        "op": "find_grep",
        "path": "src",
        "find_name": "*.py",
        "grep_pattern": "import",
        "grep_ignore_case": True,
        "grep_count": True,
    })

    # [3] find + grep 递归 + 上下文行
    #    等价于: find . -name "*.log" | xargs grep -A2 "ERROR"
    out = skill.execute({
        "op": "find_grep",
        "path": "/var/log",
        "find_name": "*.log",
        "find_recursive": True,
        "grep_pattern": "ERROR",
        "grep_context_after": 2,
    })

    # [4] find + grep 正则
    #    等价于: find . -name "*.py" -type f | xargs grep -nE "^class \w+"
    out = skill.execute({
        "op": "find_grep",
        "path": "/home/user/project",
        "find_name": "*.py",
        "find_type": "f",
        "find_recursive": True,
        "grep_pattern": r"^class \w+",
        "grep_use_regex": True,
        "grep_line_number": True,
    })

    # [5] find + grep 仅列出匹配的文件名
    #    等价于: find . -name "*.py" | xargs grep -l "pytest"
    out = skill.execute({
        "op": "find_grep",
        "path": "/home/user/project",
        "find_name": "*.py",
        "find_recursive": True,
        "grep_pattern": "pytest",
        "grep_files_with_matches": True,
    })

    # [6] find (按大小/时间) + grep
    #    等价于: find . -name "*.log" -size +1M -mtime -7 | xargs grep "ERROR"
    out = skill.execute({
        "op": "find_grep",
        "path": "/var/log",
        "find_name": "*.log",
        "find_recursive": True,
        "find_min_size": 1048576,
        "find_modified_within_days": 7,
        "grep_pattern": "ERROR",
    })

    # [7] find + grep 反转匹配
    #    等价于: find . -name "*.conf" | xargs grep -v "^#"
    out = skill.execute({
        "op": "find_grep",
        "path": "/etc",
        "find_name": "*.conf",
        "grep_pattern": "^#",
        "grep_use_regex": True,
        "grep_invert": True,
        "grep_line_number": True,
    })

------------------------------------------------------------------------------
参数说明
------------------------------------------------------------------------------

op   (str, 必填) — 管道操作名，固定为 "find_grep"
path (str, 必填) — 起始搜索目录（传给 find 和 grep 共用）

=== find 侧参数（前缀 find_） ===
    find_name               (str)   — 文件名 glob（如 "*.py"）
    find_regex              (str)   — 文件名正则
    find_type               (str)   — "f"=文件, "d"=目录
    find_recursive          (bool)  — 递归搜索子目录
    find_max_depth          (int)   — 最大深度
    find_min_depth          (int)   — 最小深度
    find_min_size           (int)   — 最小文件大小（字节）
    find_max_size           (int)   — 最大文件大小（字节）
    find_empty              (bool)  — 仅匹配空文件
    find_modified_within_days (int) — 最近 N 天内修改
    find_older_than_days    (int)   — N 天前修改
    find_limit              (int)   — find 最大结果数

=== grep 侧参数（前缀 grep_） ===
    grep_pattern            (str, 必填) — 搜索模式
    grep_ignore_case        (bool)  — 忽略大小写
    grep_line_number        (bool)  — 附带行号
    grep_invert             (bool)  — 反转匹配
    grep_count              (bool)  — 仅返回计数
    grep_files_with_matches (bool)  — 仅列文件名
    grep_use_regex          (bool)  — 正则模式
    grep_context_before     (int)   — 匹配前行数
    grep_context_after      (int)   — 匹配后行数
    grep_max_count          (int)   — grep 最大匹配数

------------------------------------------------------------------------------
返回值（ok=True 时）
------------------------------------------------------------------------------

- 默认模式:
    result = [
        {"file": "/path/to/a.py", "line": 23, "text": "# TODO: ..."},
        ...
    ]

- grep_count=True:
    result = {"total": 42}

- grep_files_with_matches=True:
    result = ["/path/to/a.py", "/path/to/b.py", ...]

------------------------------------------------------------------------------
Examples (流水线演示)
------------------------------------------------------------------------------

  PipelineOps().execute({
      "op":"find_grep","path":".","find_name":"*.py",
      "grep_pattern":"TODO","grep_line_number":true
  })
  # => {"ok": True, "result": [{"file":"test_abc.py","line":5,"text":"# TODO"}, ...], "error": None}

  PipelineOps().execute({
      "op":"find_grep","path":"src","find_name":"*.py","find_recursive":true,
      "grep_pattern":"import","grep_ignore_case":true,"grep_count":true
  })
  # => {"ok": True, "result": {"total": 18}, "error": None}

  PipelineOps().execute({
      "op":"find_grep","path":"/var/log","find_name":"*.log","find_min_size":1048576,
      "find_recursive":true,"grep_pattern":"ERROR","grep_context_after":2,"grep_line_number":true
  })
  # => {"ok": True, "result": [{"file":"/var/log/syslog","line":150,"text":"ERROR: ...",
  #       "context_after":[{"line":151,...},{"line":152,...}]}, ...], "error": None}
"""
from typing import Any

from .base import ok, err
from .find_ops import FindOps
from .grep_ops import GrepOps


class PipelineOps:
    """管道 Skill 组合器，串联 find_ops → grep_ops 实现 Unix 流水线语义。

    也承载知识图谱维护操作 (build_similarity_edges)。
    """

    def __init__(self):
        self._find = FindOps()
        self._grep = GrepOps()

    # ------------------------------------------------------------------
    #  find + grep pipeline
    # ------------------------------------------------------------------
    def execute(self, args: dict) -> dict:
        op = args.get("op")
        if op == "find_grep":
            return self._find_grep(args)
        if op == "build_similarity_edges":
            return self._build_similarity_edges(args)
        if op == "ingest":
            return self._ingest(args)
        if op == "unindex":
            return self._unindex(args)
        return err(f"unknown op: {op!r} (supported: 'find_grep', 'build_similarity_edges', 'ingest', 'unindex')")

    def _find_grep(self, args: dict) -> dict:
        pipeline_path = args.get("path")
        if not isinstance(pipeline_path, str) or not pipeline_path:
            return err("missing or empty 'path'")

        # --- 构造 find 参数 ---
        find_args: dict[str, Any] = {
            "op": "find",
            "path": pipeline_path,
        }
        _copy_param(args, "find_name",               find_args, "name")
        _copy_param(args, "find_regex",              find_args, "regex")
        _copy_param(args, "find_type",               find_args, "type")
        _copy_param(args, "find_recursive",          find_args, "recursive")
        _copy_param(args, "find_max_depth",          find_args, "max_depth")
        _copy_param(args, "find_min_depth",          find_args, "min_depth")
        _copy_param(args, "find_min_size",           find_args, "min_size")
        _copy_param(args, "find_max_size",           find_args, "max_size")
        _copy_param(args, "find_empty",              find_args, "empty")
        _copy_param(args, "find_modified_within_days", find_args, "modified_within_days")
        _copy_param(args, "find_older_than_days",    find_args, "older_than_days")
        _copy_param(args, "find_limit",              find_args, "limit")

        # 运行 find
        find_out = self._find.execute(find_args)
        if not find_out.get("ok"):
            return err(f"find failed: {find_out.get('error')}")

        found = find_out.get("result", [])
        if not found:
            return err("find returned no files")

        # 提取文件路径（仅保留文件类型）
        file_paths: list[str] = []
        for entry in found:
            if entry.get("type") == "f":
                file_paths.append(entry["path"])
        if not file_paths:
            return err("find returned no regular files")

        # --- 构造 grep 参数 ---
        grep_pattern = args.get("grep_pattern")
        if not isinstance(grep_pattern, str) or not grep_pattern:
            return err("missing or empty 'grep_pattern'")

        grep_args: dict[str, Any] = {
            "op": "search",
            "pattern": grep_pattern,
            "paths": file_paths,  # 上游 find 已精确定位文件，跳过 path/glob/recursive
        }
        _copy_param(args, "grep_ignore_case",         grep_args, "ignore_case")
        _copy_param(args, "grep_line_number",         grep_args, "line_number")
        _copy_param(args, "grep_invert",              grep_args, "invert")
        _copy_param(args, "grep_count",               grep_args, "count")
        _copy_param(args, "grep_files_with_matches",  grep_args, "files_with_matches")
        _copy_param(args, "grep_use_regex",           grep_args, "use_regex")
        _copy_param(args, "grep_context_before",      grep_args, "context_before")
        _copy_param(args, "grep_context_after",       grep_args, "context_after")
        _copy_param(args, "grep_max_count",           grep_args, "max_count")

        # 运行 grep
        grep_out = self._grep.execute(grep_args)
        return grep_out

    # ------------------------------------------------------------------
    #  build_similarity_edges
    # ------------------------------------------------------------------
    def _build_similarity_edges(self, args: dict) -> dict:
        """BM25 top-k 相似度边构建,封装 scripts.build_similarity_edges.build_edges。

        参数:
            corpus_dir  (str,  必填 — 显式传入,不读取 env,避免误操作生产 corpus)
            graph_db    (str,  必填 — 显式传入)
            top_k       (int,  默认 5)
            min_score   (float,默认 -1.0 — BM25 对不相似文档返回负分,0.0 会滤掉全部 top-k)
            clear       (bool, 默认 False — True 时先清除现有 bm25_similar 边)
        """
        from scripts.build_similarity_edges import build_edges

        corpus_dir = args.get("corpus_dir")
        graph_db = args.get("graph_db")

        if not isinstance(corpus_dir, str) or not corpus_dir.strip():
            return err("missing or empty 'corpus_dir' (must be explicitly provided)")
        if not isinstance(graph_db, str) or not graph_db.strip():
            graph_db = "rag/graph_index.db"

        top_k = args.get("top_k", 5)
        if not isinstance(top_k, int) or top_k <= 0:
            return err("'top_k' must be a positive integer")

        min_score = args.get("min_score", -1.0)
        if not isinstance(min_score, (int, float)):
            return err("'min_score' must be a number")

        clear_existing = bool(args.get("clear", False))

        try:
            stats = build_edges(
                corpus_dir=corpus_dir,
                graph_db_path=graph_db,
                top_k=top_k,
                clear_existing=clear_existing,
                min_score=float(min_score),
            )
        except Exception as e:
            return err(f"build_similarity_edges failed: {e}")

        return ok(stats)

    # ------------------------------------------------------------------
    #  ingest (manual pipeline trigger)
    # ------------------------------------------------------------------
    def _ingest(self, args: dict) -> dict:
        """Manually trigger pipeline_worker.process_file on .md file(s).

        Accepts a single .md file or a directory (processes all .md files recursively).
        Useful when the watcher is not running, or to re-index specific files.
        """
        from scripts.pipeline_worker import process_file
        from pathlib import Path

        path = args.get("path")
        if not isinstance(path, str) or not path.strip():
            return err("ingest requires a 'path', e.g. 'ingest rag/corpus/foo.md'")
        p = Path(path)
        if not p.exists():
            return err(f"file not found: {path}")

        # Single file
        if p.is_file():
            if p.suffix != ".md":
                return err(f"not a markdown file: {path}")
            try:
                return process_file(p)
            except Exception as e:
                return err(f"ingest failed: {type(e).__name__}: {e}")

        # Directory: process all .md files recursively
        md_files = sorted(p.rglob("*.md"))
        if not md_files:
            return err(f"no .md files found under: {path}")

        results = []
        ok_count = 0
        for md in md_files:
            try:
                r = process_file(md)
                if r.get("ok"):
                    ok_count += 1
                results.append({"file": str(md), "ok": r.get("ok", False),
                                "error": r.get("error")})
            except Exception as e:
                results.append({"file": str(md), "ok": False,
                                "error": f"{type(e).__name__}: {e}"})

        return ok({"total": len(md_files), "ok": ok_count,
                   "failed": len(md_files) - ok_count, "details": results})

    # ------------------------------------------------------------------
    #  unindex (delete file from all indexes)
    # ------------------------------------------------------------------
    def _unindex(self, args: dict) -> dict:
        """Remove a file's entries from FTS5, graph_index, and chunks.

        Wraps pipeline_worker.delete_file_indexes.
        """
        from scripts.pipeline_worker import delete_file_indexes
        from pathlib import Path

        path = args.get("path")
        if not isinstance(path, str) or not path.strip():
            return err("unindex requires a 'path', e.g. 'unindex rag/corpus/foo.md'")
        p = Path(path)
        try:
            return delete_file_indexes(p)
        except Exception as e:
            return err(f"unindex failed: {type(e).__name__}: {e}")


def _copy_param(src: dict, src_key: str, dst: dict, dst_key: str) -> None:
    """如果 src 中存在 src_key 且值不为 None，则复制到 dst[dst_key]。"""
    if src_key in src and src[src_key] is not None:
        dst[dst_key] = src[src_key]