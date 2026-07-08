# -*- coding: utf-8 -*-
"""Linux find 风格的文件查找 Skill。

在指定目录下按名称、类型、大小、时间等条件查找文件/目录。
所有操作返回 ai-agent-core 标准信封：
    {"ok": True,  "result": <list[dict]>, "error": None}
    {"ok": False, "result": None, "error": "<msg>"}

------------------------------------------------------------------------------
Usage (Skill 接入)
------------------------------------------------------------------------------

    from skills.find_ops import FindOps
    skill = FindOps()

    # [1] 按文件名 glob 查找
    out = skill.execute({
        "op": "find",
        "path": "/home/user/project",
        "name": "*.py",
    })

    # [2] 递归查找所有目录
    out = skill.execute({
        "op": "find",
        "path": "/home/user/project",
        "type": "d",
        "recursive": True,
    })

    # [3] 按名称 + 类型 + 深度限制
    out = skill.execute({
        "op": "find",
        "path": "/home/user/project",
        "name": "test_*.py",
        "type": "f",
        "max_depth": 3,
        "recursive": True,
    })

    # [4] 正则匹配文件名
    out = skill.execute({
        "op": "find",
        "path": "/home/user/project",
        "regex": r"^[A-Z].*\\.py$",
        "recursive": True,
    })

    # [5] 按最小大小查找（字节）
    out = skill.execute({
        "op": "find",
        "path": "/var/log",
        "min_size": 1048576,   # >= 1 MB
        "recursive": True,
    })

    # [6] 按修改时间查找（最近 7 天）
    out = skill.execute({
        "op": "find",
        "path": "/home/user/project",
        "name": "*.log",
        "modified_within_days": 7,
        "recursive": True,
    })

    # [7] 空文件 / 空目录
    out = skill.execute({
        "op": "find",
        "path": "/home/user/project",
        "empty": True,
        "recursive": True,
    })

    # [8] 组合条件：最近 30 天修改、大于 10KB 的 .py 文件
    out = skill.execute({
        "op": "find",
        "path": "/home/user/project",
        "name": "*.py",
        "min_size": 10240,
        "modified_within_days": 30,
        "recursive": True,
    })

------------------------------------------------------------------------------
参数说明
------------------------------------------------------------------------------

op   (str, 必填) — 操作名，固定为 "find"
path (str, 必填) — 起始搜索目录路径

可选参数:
    name                 (str)   — 文件名 glob 匹配（如 "*.py", "test_*"）
    regex                (str)   — 文件名正则匹配（与 name 二选一，同时指定时 regex 优先）
    type                 (str)   — 类型过滤: "f"=文件, "d"=目录
    recursive            (bool)  — 递归搜索子目录（默认 False，仅搜索顶层）
    max_depth            (int)   — 最大递归深度（与 recursive 一起使用）
    min_depth            (int)   — 最小递归深度
    min_size             (int)   — 最小文件大小（字节）
    max_size             (int)   — 最大文件大小（字节）
    empty                (bool)  — 仅匹配空文件或空目录
    modified_within_days (int)   — 最近 N 天内修改过的文件/目录
    older_than_days      (int)   — 修改时间早于 N 天前的文件/目录
    limit                (int)   — 最大返回结果数

------------------------------------------------------------------------------
返回值（ok=True 时）
------------------------------------------------------------------------------

result = [
    {
        "path":       "/home/user/project/src/main.py",
        "name":       "main.py",
        "type":       "f",
        "size":       2048,
        "modified":   "2025-07-01T12:00:00",
    },
    ...
]

------------------------------------------------------------------------------
Examples (CLI 风格演示)
------------------------------------------------------------------------------

  FindOps().execute({"op":"find","path":"/src","name":"*.py","recursive":true})
  # => {"ok": True, "result": [{"path":"/src/main.py","name":"main.py","type":"f","size":1024,...}, ...], "error": None}

  FindOps().execute({"op":"find","path":"/home/user","type":"d","max_depth":2})
  # => {"ok": True, "result": [{"path":"/home/user/docs","name":"docs","type":"d","size":4096,...}, ...], "error": None}

  FindOps().execute({"op":"find","path":"/var/log","name":"*.log","min_size":1048576,"recursive":true})
  # => {"ok": True, "result": [{"path":"/var/log/syslog","name":"syslog","type":"f","size":2359296,...}, ...], "error": None}

------------------------------------------------------------------------------
CLI Usage
------------------------------------------------------------------------------

  # 按文件名查找
  python find_ops.py /home/user/project -name "*.py"

  # 递归查找所有目录，限制深度
  python find_ops.py . -type d -maxdepth 2

  # 查找最近7天修改过的日志文件
  python find_ops.py /var/log -name "*.log" -mtime -7

  # 查找大于 1MB 的文件
  python find_ops.py /home/user/project -size +1048576

  # 查找空文件/空目录
  python find_ops.py /home/user/project -empty

  # 正则匹配文件名
  python find_ops.py /home/user/project -regex "^[A-Z].*\\.py$"

  # 组合条件：最近30天修改、大于10KB的 .py 文件
  python find_ops.py /home/user/project -name "*.py" -size +10240 -mtime -30
"""
import fnmatch
import re as _re
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from .base import ok, err
except ImportError:
    from base import ok, err  # type: ignore[no-redef]


class FindOps:
    """在目录下按条件查找文件/目录，模拟 find 命令行为。"""

    _STAT_KEYS = ("st_size", "st_mtime")

    def execute(self, args: dict) -> dict:
        op = args.get("op")
        if op != "find":
            return err(f"unknown op: {op!r} (supported: 'find')")

        path_arg = args.get("path")
        if not isinstance(path_arg, str) or not path_arg:
            return err("missing or empty 'path'")

        root = Path(path_arg).expanduser().resolve()
        if not root.exists():
            return err(f"path not found: {path_arg}")
        if not root.is_dir():
            return err(f"path is not a directory: {path_arg}")

        # --- 解析选项 ---
        name_pat   = args.get("name")
        regex_pat  = args.get("regex")
        entry_type = args.get("type")
        recursive  = bool(args.get("recursive", False))
        max_depth  = args.get("max_depth")
        min_depth  = args.get("min_depth")
        min_size   = args.get("min_size")
        max_size   = args.get("max_size")
        empty_only = bool(args.get("empty", False))
        within_days = args.get("modified_within_days")
        older_days  = args.get("older_than_days")
        limit      = args.get("limit")

        if max_depth is not None and (not isinstance(max_depth, int) or max_depth < 0):
            return err(f"invalid 'max_depth': {max_depth!r}")
        if min_depth is not None and (not isinstance(min_depth, int) or min_depth < 0):
            return err(f"invalid 'min_depth': {min_depth!r}")
        if min_size is not None and (not isinstance(min_size, int) or min_size < 0):
            return err(f"invalid 'min_size': {min_size!r}")
        if max_size is not None and (not isinstance(max_size, int) or max_size < 0):
            return err(f"invalid 'max_size': {max_size!r}")
        if entry_type is not None and entry_type not in ("f", "d"):
            return err(f"invalid 'type': {entry_type!r} (expected 'f' or 'd')")
        if within_days is not None and (not isinstance(within_days, int) or within_days <= 0):
            return err(f"invalid 'modified_within_days': {within_days!r}")
        if older_days is not None and (not isinstance(older_days, int) or older_days <= 0):
            return err(f"invalid 'older_than_days': {older_days!r}")
        if limit is not None and (not isinstance(limit, int) or limit <= 0):
            return err(f"invalid 'limit': {limit!r}")

        # --- 编译名称匹配 ---
        if regex_pat:
            try:
                _regex = _re.compile(regex_pat)
            except _re.error as e:
                return err(f"invalid regex pattern: {e}")
            def _name_matches(p: Path) -> bool:
                return bool(_regex.search(p.name))
        elif name_pat:
            def _name_matches(p: Path) -> bool:
                return fnmatch.fnmatch(p.name, name_pat)
        else:
            def _name_matches(p: Path) -> bool:
                return True

        # --- 时间阈值 ---
        ref_time = datetime.now(timezone.utc).timestamp()
        after_ts: float | None = None
        before_ts: float | None = None
        if within_days is not None:
            after_ts = (datetime.now(timezone.utc) - timedelta(days=within_days)).timestamp()
        if older_days is not None:
            before_ts = (datetime.now(timezone.utc) - timedelta(days=older_days)).timestamp()

        # --- 搜索 ---
        results: list[dict] = []
        walker = root.rglob("*") if recursive else root.glob("*")

        for p in walker:
            if limit is not None and len(results) >= limit:
                break

            # 跳过 root 自身
            if p == root:
                continue

            # 递归深度控制
            if recursive and (max_depth is not None or min_depth is not None):
                depth = len(p.relative_to(root).parts)
                if min_depth is not None and depth < min_depth:
                    continue
                if max_depth is not None and depth > max_depth:
                    if p.is_dir():
                        # 不再深入此目录下的内容，但其它同级仍继续
                        # 由于 rglob 是遍历所有，这里需要跳过子目录
                        # 简单方法：对于超过 max_depth 的，只保留当前层级结果
                        continue
                    continue

            # 类型过滤
            if entry_type == "f" and not p.is_file():
                continue
            if entry_type == "d" and not p.is_dir():
                continue

            # 名称匹配
            if not _name_matches(p):
                continue

            # 获取 stat
            try:
                st = p.stat()
            except OSError:
                continue

            # 大小过滤（仅对文件有效，对目录跳过）
            if p.is_file():
                if min_size is not None and st.st_size < min_size:
                    continue
                if max_size is not None and st.st_size > max_size:
                    continue
                if empty_only and st.st_size != 0:
                    continue
            elif p.is_dir() and empty_only:
                try:
                    if any(p.iterdir()):
                        continue
                except OSError:
                    continue

            # 时间过滤
            mtime = st.st_mtime
            if after_ts is not None and mtime < after_ts:
                continue
            if before_ts is not None and mtime > before_ts:
                continue

            # --- 组装结果 ---
            entry: dict = {
                "path": str(p),
                "name": p.name,
                "type": "d" if p.is_dir() else "f",
            }
            if p.is_file():
                entry["size"] = st.st_size
            else:
                try:
                    entry["size"] = st.st_size  # 目录大小（通常是 4096）
                except Exception:
                    entry["size"] = 0
            try:
                entry["modified"] = datetime.fromtimestamp(
                    mtime, tz=timezone.utc
                ).isoformat()
            except Exception:
                entry["modified"] = ""

            results.append(entry)

        return ok(results)


# ── CLI 入口 ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    path = "."
    params: dict = {"op": "find", "path": ".", "recursive": True}

    i = 0
    while i < len(args):
        a = args[i]
        if not a.startswith("-"):
            # 非选项视为 path
            path = a
            params["path"] = path
            i += 1
            continue

        if a == "-name":
            i += 1
            if i < len(args):
                params["name"] = args[i]
        elif a == "-regex":
            i += 1
            if i < len(args):
                params["regex"] = args[i]
        elif a == "-type":
            i += 1
            if i < len(args):
                params["type"] = args[i]
        elif a == "-size":
            i += 1
            if i < len(args):
                size_str = args[i]
                if size_str.startswith("+"):
                    params["min_size"] = int(size_str[1:])
                elif size_str.startswith("-"):
                    params["max_size"] = int(size_str[1:])
                else:
                    # 精确大小: min=max
                    params["min_size"] = int(size_str)
                    params["max_size"] = int(size_str)
        elif a == "-mtime":
            i += 1
            if i < len(args):
                mtime_str = args[i]
                if mtime_str.startswith("-"):
                    # -mtime -N => 最近 N*24h 内修改，近似为 modified_within_days
                    params["modified_within_days"] = abs(int(mtime_str))
                elif mtime_str.startswith("+"):
                    params["older_than_days"] = abs(int(mtime_str))
                else:
                    params["older_than_days"] = int(mtime_str)
        elif a == "-maxdepth":
            i += 1
            if i < len(args):
                params["max_depth"] = int(args[i])
                params["recursive"] = True
        elif a == "-mindepth":
            i += 1
            if i < len(args):
                params["min_depth"] = int(args[i])
                params["recursive"] = True
        elif a == "-empty":
            params["empty"] = True
        elif a in ("-maxdepth",):
            pass  # 已在上面处理
        else:
            print(f"find_ops: unknown option {a}", file=sys.stderr)
            sys.exit(1)
        i += 1

    skill = FindOps()
    result = skill.execute(params)
    if result["ok"]:
        for entry in result["result"]:
            print(entry["path"])
    else:
        print(f"find_ops: {result['error']}", file=sys.stderr)
        sys.exit(1)