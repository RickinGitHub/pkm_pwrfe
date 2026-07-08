# -*- coding: utf-8 -*-
"""Linux grep 风格的文本搜索 Skill。

在文件或目录中按正则/子串搜索匹配行，支持常用 grep 选项。
所有操作返回 ai-agent-core 标准信封：
    {"ok": True,  "result": <list[dict]|int|str>, "error": None}
    {"ok": False, "result": None, "error": "<msg>"}

------------------------------------------------------------------------------
Usage (Skill 接入)
------------------------------------------------------------------------------

    from skills.grep_ops import GrepOps
    skill = GrepOps()

    # [1] 在单个文件中搜索
    out = skill.execute({
        "op": "search",
        "pattern": "error",
        "path": "/var/log/app.log",
    })

    # [2] 在目录下搜索所有 .py 文件
    out = skill.execute({
        "op": "search",
        "pattern": "TODO",
        "path": "/home/user/project",
        "glob": "*.py",
        "recursive": True,
        "line_number": True,
    })

    # [3] 忽略大小写 + 上下文行
    out = skill.execute({
        "op": "search",
        "pattern": "import os",
        "path": "/home/user/project",
        "glob": "*.py",
        "recursive": True,
        "ignore_case": True,
        "context_after": 2,
    })

    # [4] 反转匹配（显示不包含模式的行）
    out = skill.execute({
        "op": "search",
        "pattern": "^#",
        "path": "/path/to/config.conf",
        "invert": True,
    })

    # [5] 仅计数
    out = skill.execute({
        "op": "search",
        "pattern": "def test_",
        "path": "/home/user/tests",
        "glob": "*.py",
        "recursive": True,
        "count": True,
    })

    # [6] 仅列出匹配的文件名
    out = skill.execute({
        "op": "search",
        "pattern": "pytest",
        "path": "/home/user/project",
        "recursive": True,
        "files_with_matches": True,
    })

------------------------------------------------------------------------------
参数说明
------------------------------------------------------------------------------

op      (str, 必填) — 操作名，固定为 "search"
pattern (str, 必填) — 搜索模式（默认子串匹配；设置 use_regex=True 启用正则）
path    (str, 条件必填) — 文件路径或目录路径（未传 paths 时必填，传了 paths 则忽略）
paths   (list[str])    — 指定文件路径列表（如 pipeline 传入的 find 结果集）; 传入时忽略 path/glob/recursive

可选参数:
    glob                (str)   — 当 path 为目录时，按 glob 过滤文件（如 "*.py"）
    ignore_case         (bool)  — 忽略大小写（默认 False）
    line_number         (bool)  — 结果中附带行号（默认 False）
    invert              (bool)  — 反转匹配：返回不包含模式的行（默认 False）
    count               (bool)  — 仅返回匹配总数，不返回具体行（默认 False）
    files_with_matches  (bool)  — 仅返回有匹配的文件名列表（默认 False）
    recursive           (bool)  — path 为目录时递归搜索子目录（默认 False）
    use_regex           (bool)  — 将 pattern 作为正则表达式（默认 False）
    context_before      (int)   — 每个匹配前显示的行数
    context_after       (int)   — 每个匹配后显示的行数
    max_count           (int)   — 最大匹配数，达到后停止搜索

------------------------------------------------------------------------------
返回值（ok=True 时）
------------------------------------------------------------------------------

- 默认模式:
    result = [
        {"file": "app.py", "line": 23, "text": "    logger.error(msg)", "context_before": [...], "context_after": [...]},
        ...
    ]

- count=True:
    result = {"total": 42}

- files_with_matches=True:
    result = ["app.py", "utils.py", ...]

------------------------------------------------------------------------------
Examples (CLI 风格演示)
------------------------------------------------------------------------------

  GrepOps().execute({"op":"search","pattern":"error","path":"/var/log/syslog"})
  # => {"ok": True, "result": [{"file": "syslog", "line": 15, "text": "error: disk full", ...}], "error": None}

  GrepOps().execute({"op":"search","pattern":"TODO","path":"src","glob":"*.py","recursive":true,"line_number":true})
  # => {"ok": True, "result": [{"file": "src/main.py", "line": 42, "text": "# TODO: refactor"}, ...], "error": None}

  GrepOps().execute({"op":"search","pattern":"error","path":"/var/log/app.log","ignore_case":true,"count":true})
  # => {"ok": True, "result": {"total": 14}, "error": None}

------------------------------------------------------------------------------
CLI Usage
------------------------------------------------------------------------------

  # 在单个文件中搜索（显示行号）
  python grep_ops.py -n "error" /var/log/app.log

  # 递归搜索目录（行号 + 递归 + 静默）
  python grep_ops.py -nrs "TODO" /home/user/project

  # 忽略大小写 + 上下文（前后各2行）
  python grep_ops.py -ni -C 2 "import os" /home/user/project

  # 递归搜索，仅计数
  python grep_ops.py -cr "def test_" tests/

  # 递归搜索，仅列出匹配的文件名
  python grep_ops.py -rl "pytest" /home/user/project

  # 反转匹配（显示不含注释的行）
  python grep_ops.py -v "^#" config.conf

  # 正则匹配（递归）
  python grep_ops.py -nrE "def\\s+test_\\w+" tests/

  # 限制最大匹配数
  python grep_ops.py -nrsm 5 "error" /var/log/
"""
import re
from pathlib import Path

try:
    from .base import ok, err
except ImportError:
    from base import ok, err  # type: ignore[no-redef]


class GrepOps:
    """在文件/目录中搜索模式匹配行，模拟 grep 行为。"""

    def execute(self, args: dict) -> dict:
        op = args.get("op")
        if op != "search":
            return err(f"unknown op: {op!r} (supported: 'search')")

        pattern = args.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return err("missing or empty 'pattern'")

        # --- 解析选项 ---
        glob_pat      = args.get("glob")
        ignore_case   = bool(args.get("ignore_case", False))
        line_number   = bool(args.get("line_number", False))
        invert        = bool(args.get("invert", False))
        count_only    = bool(args.get("count", False))
        files_only    = bool(args.get("files_with_matches", False))
        recursive     = bool(args.get("recursive", False))
        use_regex     = bool(args.get("use_regex", False))
        context_before = int(args.get("context_before", 0))
        context_after  = int(args.get("context_after", 0))
        max_count     = args.get("max_count")

        if max_count is not None and not isinstance(max_count, int):
            return err(f"invalid 'max_count': {max_count!r}")
        if context_before < 0 or context_after < 0:
            return err("context_before / context_after cannot be negative")

        # --- 编译匹配函数 ---
        if use_regex:
            flags = re.IGNORECASE if ignore_case else 0
            try:
                pat = re.compile(pattern, flags)
            except re.error as e:
                return err(f"invalid regex pattern: {e}")
            def _matches(line: str) -> bool:
                return bool(pat.search(line))
        else:
            if ignore_case:
                _pat_lower = pattern.lower()
                def _matches(line: str) -> bool:
                    return _pat_lower in line.lower()
            else:
                def _matches(line: str) -> bool:
                    return pattern in line

        # --- 收集要搜索的文件列表 ---
        files: list[Path] = []

        # 优先使用 paths 参数（由 pipeline_ops 等上游传入的多文件路径列表）
        explicit_paths = args.get("paths")
        if isinstance(explicit_paths, list) and explicit_paths:
            for p in explicit_paths:
                fp = Path(p).expanduser().resolve()
                if fp.is_file():
                    files.append(fp)
            if not files:
                return err("no accessible files in 'paths'")
        else:
            path_arg = args.get("path")
            if not isinstance(path_arg, str) or not path_arg:
                return err("missing or empty 'path'")

            root = Path(path_arg).expanduser().resolve()
            if not root.exists():
                return err(f"path not found: {path_arg}")

            if root.is_file():
                files = [root]
            elif root.is_dir():
                rglob = root.rglob if recursive else root.glob
                if glob_pat:
                    files = sorted(p for p in rglob(glob_pat) if p.is_file())
                else:
                    files = sorted(p for p in rglob("*") if p.is_file())
                if not files:
                    return err(f"no files matched in: {path_arg}")
            else:
                return err(f"not a file or directory: {path_arg}")

        # --- 搜索 ---
        total_count = 0
        matched_files: list[str] = []
        results: list[dict] = []

        for fp in files:
            if max_count is not None and total_count >= max_count:
                break
            try:
                all_lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception as e:
                results.append({
                    "file": str(fp),
                    "error": f"{type(e).__name__}: {e}",
                })
                continue

            file_results: list[dict] = []
            for idx, line in enumerate(all_lines, start=1):
                if max_count is not None and total_count >= max_count:
                    break
                hit = _matches(line)
                if invert:
                    hit = not hit
                if not hit:
                    continue

                total_count += 1
                entry: dict = {}
                if line_number:
                    entry["line"] = idx
                entry["text"] = line

                # --- 上下文行 ---
                if context_before > 0 or context_after > 0:
                    start_b = max(0, idx - 1 - context_before)
                    end_b   = max(0, idx - 1)
                    start_a = idx
                    end_a   = min(len(all_lines), idx + context_after)

                    if context_before > 0:
                        entry["context_before"] = [
                            {"line": ln, "text": all_lines[ln - 1]}
                            for ln in range(start_b + 1, end_b + 1)
                        ]
                    if context_after > 0:
                        entry["context_after"] = [
                            {"line": ln, "text": all_lines[ln - 1]}
                            for ln in range(start_a + 1, end_a + 1)
                        ]
                    # 只有在 line_number 为 False 时才补充当前行号（用于上下文定位）
                    if not line_number:
                        entry["line"] = idx

                if files_only:
                    entry["file"] = str(fp)
                file_results.append(entry)

            if file_results:
                matched_files.append(str(fp))
                if not files_only:
                    for r in file_results:
                        r["file"] = str(fp)
                    results.extend(file_results)

        # --- 组装返回值 ---
        if count_only:
            return ok({"total": total_count})
        if files_only:
            return ok(matched_files)
        return ok(results)


# ── CLI 入口 ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import os

    argv = sys.argv[1:]
    if not argv:
        print("usage: python grep_ops.py [options] <pattern> [path]", file=sys.stderr)
        sys.exit(1)

    # 解析选项与位置参数
    pattern = None
    path = None
    params: dict = {"op": "search", "line_number": True, "recursive": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if not a.startswith("-"):
            if pattern is None:
                pattern = a
            elif path is None:
                path = a
            else:
                # 多余位置参数视为额外路径，这里简单报错
                print(f"grep_ops: unexpected argument {a}", file=sys.stderr)
                sys.exit(1)
            i += 1
            continue

        # 长选项
        if a.startswith("--"):
            opt = a[2:]
            if opt == "include":
                i += 1
                if i < len(argv):
                    params["glob"] = argv[i]
            elif opt == "ignore-case":
                params["ignore_case"] = True
            elif opt == "invert-match":
                params["invert"] = True
            elif opt == "count":
                params["count"] = True
            elif opt == "files-with-matches":
                params["files_with_matches"] = True
            elif opt == "recursive":
                params["recursive"] = True
            elif opt == "regex":
                params["use_regex"] = True
            elif opt == "max-count":
                i += 1
                if i < len(argv):
                    params["max_count"] = int(argv[i])
            elif opt in ("context", "after-context", "before-context"):
                i += 1
                if i < len(argv):
                    ctx = int(argv[i])
                    if opt == "context":
                        params["context_before"] = ctx
                        params["context_after"] = ctx
                    elif opt == "after-context":
                        params["context_after"] = ctx
                    else:
                        params["context_before"] = ctx
            else:
                print(f"grep_ops: unknown option --{opt}", file=sys.stderr)
                sys.exit(1)
            i += 1
            continue

        # 短选项
        opts = a[1:]
        j = 0
        while j < len(opts):
            o = opts[j]
            if o == "i":
                params["ignore_case"] = True
            elif o == "v":
                params["invert"] = True
            elif o == "c":
                params["count"] = True
            elif o == "l":
                params["files_with_matches"] = True
            elif o == "n":
                params["line_number"] = True
            elif o == "r":
                params["recursive"] = True
            elif o == "s":
                # suppress error messages - already handled
                pass
            elif o == "H":
                # always print filename - default behavior
                pass
            elif o == "m":
                j += 1
                if j < len(opts):
                    params["max_count"] = int(opts[j])
                else:
                    print("grep_ops: -m requires a number", file=sys.stderr)
                    sys.exit(1)
            elif o == "A":
                j += 1
                if j < len(opts):
                    params["context_after"] = int(opts[j])
                else:
                    print("grep_ops: -A requires a number", file=sys.stderr)
                    sys.exit(1)
            elif o == "B":
                j += 1
                if j < len(opts):
                    params["context_before"] = int(opts[j])
                else:
                    print("grep_ops: -B requires a number", file=sys.stderr)
                    sys.exit(1)
            elif o == "C":
                j += 1
                if j < len(opts):
                    ctx = int(opts[j])
                    params["context_before"] = ctx
                    params["context_after"] = ctx
                else:
                    print("grep_ops: -C requires a number", file=sys.stderr)
                    sys.exit(1)
            elif o == "e":
                j += 1
                if j < len(opts):
                    pattern = opts[j]
                else:
                    print("grep_ops: -e requires a pattern", file=sys.stderr)
                    sys.exit(1)
            elif o == "E":
                params["use_regex"] = True
            else:
                print(f"grep_ops: unknown option -{o}", file=sys.stderr)
                sys.exit(1)
            j += 1
        i += 1

    if pattern is None:
        print("grep_ops: missing pattern", file=sys.stderr)
        sys.exit(1)

    if path is None:
        path = "."
    params["pattern"] = pattern
    params["path"] = path

    # 如果 path 是目录，但未设 recursive 且未设 glob，默认设为当前目录匹配
    if os.path.isdir(path) and not params.get("recursive") and not params.get("glob"):
        # 非递归下 glob("*") 找出顶层文件
        params["glob"] = "*"

    skill = GrepOps()
    result = skill.execute(params)

    if not result["ok"]:
        print(f"grep_ops: {result['error']}", file=sys.stderr)
        sys.exit(1)

    data = result["result"]

    # count 模式
    if params.get("count"):
        print(data["total"])
        sys.exit(0)

    # files_with_matches 模式
    if params.get("files_with_matches"):
        for f in data:
            print(f)
        sys.exit(0)

    # 默认输出
    for entry in data:
        fname = entry.get("file", "")
        lineno = f"{entry['line']}:" if entry.get("line") else ""
        # context lines
        if "context_before" in entry:
            for cb in entry["context_before"]:
                print(f"{fname}:{cb['line']}-{cb['text']}")
        text = entry.get("text", "")
        print(f"{fname}:{lineno}{text}")
        if "context_after" in entry:
            for ca in entry["context_after"]:
                print(f"{fname}:{ca['line']}-{ca['text']}")