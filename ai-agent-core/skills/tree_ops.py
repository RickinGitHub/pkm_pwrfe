# -*- coding: utf-8 -*-
"""Linux tree 风格的目录树展示 Skill。

以树形结构列出目录内容，支持常用 tree 选项。
所有操作返回 ai-agent-core 标准信封：
    {"ok": True,  "result": <str|list[dict]>, "error": None}
    {"ok": False, "result": None, "error": "<msg>"}

------------------------------------------------------------------------------
Usage (Skill 接入)
------------------------------------------------------------------------------

    from skills.tree_ops import TreeOps
    skill = TreeOps()

    # [1] 基础树形展示
    out = skill.execute({"op": "tree", "path": "/home/user/project"})

    # [2] 限制深度
    out = skill.execute({"op": "tree", "path": "/home/user/project", "max_depth": 2})

    # [3] 只显示目录
    out = skill.execute({"op": "tree", "path": "/home/user/project", "dirs_only": True})

    # [4] 显示隐藏文件 + 大小
    out = skill.execute({"op": "tree", "path": "/home/user/project", "all_files": True, "show_size": True})

    # [5] 按 glob 过滤
    out = skill.execute({"op": "tree", "path": "/home/user/project", "pattern": "*.py"})

    # [6] 忽略某些文件
    out = skill.execute({"op": "tree", "path": "/home/user/project", "ignore": "*.pyc,__pycache__"})

    # [7] 返回结构化数据（不生成字符串）
    out = skill.execute({"op": "tree", "path": "/home/user/project", "raw": True})

------------------------------------------------------------------------------
参数说明
------------------------------------------------------------------------------

op        (str, 必填) — 操作名，固定为 "tree"
path      (str, 必填) — 起始目录路径

可选参数:
    max_depth   (int)   — 最大递归深度（默认无限制）
    dirs_only   (bool)  — 仅显示目录（默认 False）
    all_files   (bool)  — 显示隐藏文件/目录（默认 False）
    show_size   (bool)  — 显示文件大小（默认 False）
    human_size  (bool)  — 人类可读的大小格式（如 1K, 2.3M），需 show_size=True
    full_path   (bool)  — 每个条目前显示完整路径前缀（默认 False）
    pattern     (str)   — 仅显示匹配 glob 的文件（逗号分隔多个）
    ignore      (str)   — 忽略匹配 glob 的文件（逗号分隔多个）
    noreport    (bool)  — 不显示末尾统计摘要（默认 False）
    raw         (bool)  — 返回结构化 list[dict] 而非渲染字符串（默认 False）

------------------------------------------------------------------------------
返回值（ok=True 时）
------------------------------------------------------------------------------

raw=False（默认）:
    result = ".\n├── agent.py\n├── skills\n│   ├── base.py\n│   └── find_ops.py\n└── tests\n    └── test_agent.py\n\n2 directories, 3 files"

raw=True:
    result = [
        {"name": "agent.py", "type": "f", "depth": 1, "size": 14782, ...},
        {"name": "skills", "type": "d", "depth": 1, "children": [...]},
        ...
    ]

------------------------------------------------------------------------------
Examples (CLI 风格演示)
------------------------------------------------------------------------------

  ------------------------------------------------------------------------------
CLI Usage
------------------------------------------------------------------------------

  # 基础树形展示（当前目录）
  python tree_ops.py

  # 指定目录
  python tree_ops.py /home/user/project

  # 限制深度为2层
  python tree_ops.py -L 2 /home/user/project

  # 只显示目录
  python tree_ops.py -d /home/user/project

  # 显示所有文件（含隐藏）+ 文件大小 + 人类可读
  python tree_ops.py -a -s -h /home/user/project

  # 按 glob 过滤（仅 .py 文件）
  python tree_ops.py -P "*.py" /home/user/project

  # 忽略某些文件
  python tree_ops.py -I "*.pyc,__pycache__" /home/user/project

  # 组合使用：深度3层、显示隐藏、大小、仅 .py、忽略测试文件
  python tree_ops.py -L 3 -a -s -P "*.py" -I "test_*" /home/user/project

  # 不显示末尾统计报告
  python tree_ops.py --noreport /home/user/project
"""
import fnmatch
from pathlib import Path
from typing import Any

try:
    from .base import ok, err
except ImportError:
    from base import ok, err  # type: ignore[no-redef]

# ── 渲染常量 ────────────────────────────────────────────────────────
_PIPE     = "│   "
_TEE      = "├── "
_ELBOW    = "└── "
_SPACE    = "    "

_UNIT_SUFFIXES = ["B", "K", "M", "G", "T", "P"]


def _human_size(n: int) -> str:
    """字节数转为人类可读格式。"""
    if n < 1024:
        return str(n)
    size: float = float(n)
    for suffix in _UNIT_SUFFIXES[1:]:
        size /= 1024.0
        if size < 1024:
            return f"{size:.1f}{suffix}" if size < 10 else f"{int(size)}{suffix}"
    return f"{size:.1f}P"


class TreeOps:
    """以树形结构展示目录内容，模拟 tree 命令行为。"""

    def execute(self, args: dict) -> dict:
        op = args.get("op")
        if op != "tree":
            return err(f"unknown op: {op!r} (supported: 'tree')")

        path_arg = args.get("path")
        if not isinstance(path_arg, str) or not path_arg:
            return err("missing or empty 'path'")

        root = Path(path_arg).expanduser().resolve()
        if not root.exists():
            return err(f"path not found: {path_arg}")
        if not root.is_dir():
            return err(f"path is not a directory: {path_arg}")

        # --- 解析选项 ---
        max_depth: int | None = args.get("max_depth")
        dirs_only   = bool(args.get("dirs_only", False))
        all_files   = bool(args.get("all_files", False))
        show_size   = bool(args.get("show_size", False))
        human_size  = bool(args.get("human_size", False))
        full_path   = bool(args.get("full_path", False))
        raw         = bool(args.get("raw", False))
        noreport    = bool(args.get("noreport", False))

        pattern_str = args.get("pattern", "")
        ignore_str  = args.get("ignore", "")

        if max_depth is not None and (not isinstance(max_depth, int) or max_depth < 0):
            return err(f"invalid 'max_depth': {max_depth!r}")

        # 解析 glob 过滤
        _patterns = [p.strip() for p in pattern_str.split(",") if p.strip()]
        _ignores  = [p.strip() for p in ignore_str.split(",") if p.strip()]

        # --- 递归构建树节点 ---
        tree, dir_count, file_count = _scan_dir(
            root, root, 0, max_depth, dirs_only, all_files,
            show_size, human_size, full_path, _patterns, _ignores,
        )

        if raw:
            return ok({"tree": tree, "dirs": dir_count, "files": file_count})

        # --- 渲染为字符串 ---
        lines: list[str] = []
        _render_node(tree, "", lines, root.name if root.name else str(root))
        report = ""
        if not noreport:
            d_label = "directory" if dir_count == 1 else "directories"
            if dirs_only:
                report = f"\n{dir_count} {d_label}"
            else:
                f_label = "file" if file_count == 1 else "files"
                report = f"\n{dir_count} {d_label}, {file_count} {f_label}"
        return ok("\n".join(lines) + report)


def _scan_dir(
    root: Path,
    entry: Path,
    depth: int,
    max_depth: int | None,
    dirs_only: bool,
    all_files: bool,
    show_size: bool,
    human_size: bool,
    full_path: bool,
    patterns: list[str],
    ignores: list[str],
) -> tuple[dict, int, int]:
    """递归扫描目录，返回 (节点, 目录计数, 文件计数)。"""
    node: dict[str, Any] = {
        "name": entry.name or str(entry),
        "path": str(entry),
        "type": "d",
        "depth": depth,
    }
    if full_path:
        node["full_path"] = str(entry)

    if max_depth is not None and depth >= max_depth:
        node["truncated"] = True
        return node, 0, 0

    try:
        items = sorted(entry.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        node["error"] = "Permission denied"
        return node, 1, 0
    except OSError as e:
        node["error"] = str(e)
        return node, 1, 0

    children: list[dict] = []
    dir_count = 0
    file_count = 0

    for child in items:
        name = child.name

        # 隐藏文件过滤
        if not all_files and name.startswith("."):
            continue

        # ignore 模式
        if _match_any(name, ignores):
            continue

        if child.is_dir():
            sub_node, s_dir, s_file = _scan_dir(
                root, child, depth + 1, max_depth, dirs_only, all_files,
                show_size, human_size, full_path, patterns, ignores,
            )
            if not dirs_only or sub_node.get("type") == "d":
                children.append(sub_node)
                dir_count += s_dir + 1
                file_count += s_file
        else:
            if dirs_only:
                continue
            # 文件 pattern 过滤（仅对文件生效）
            if patterns and not _match_any(name, patterns):
                continue

            try:
                st = child.stat()
                size_val = st.st_size
            except OSError:
                size_val = 0

            file_node: dict[str, Any] = {
                "name": name,
                "path": str(child),
                "type": "f",
                "depth": depth + 1,
                "size": size_val,
            }
            if full_path:
                file_node["full_path"] = str(child)
            if show_size:
                file_node["display_size"] = _human_size(size_val) if human_size else str(size_val)
            children.append(file_node)
            file_count += 1

    node["children"] = children
    return node, dir_count, file_count


def _render_node(
    node: dict,
    prefix: str,
    lines: list[str],
    label: str,
) -> None:
    """将树节点渲染为 tree 风格的字符串行。"""
    # 根节点
    if node.get("depth", 0) == 0:
        size_part = _size_label(node)
        extra = _extra_label(node)
        lines.append(label + extra + size_part)
        children = node.get("children", [])
        for i, child in enumerate(children):
            is_last = (i == len(children) - 1)
            connector = _ELBOW if is_last else _TEE
            new_prefix = _SPACE if is_last else _PIPE
            _render_child(child, prefix + connector, prefix + new_prefix, lines)
        return

    _render_child(node, prefix, prefix, lines)


def _render_child(
    node: dict,
    self_prefix: str,
    child_prefix: str,
    lines: list[str],
) -> None:
    """渲染子节点及其子树。"""
    label = node.get("name", "")
    size_part = _size_label(node)
    extra = _extra_label(node)
    if node.get("type") == "d":
        label += "/"
    lines.append(self_prefix + label + extra + size_part)

    children = node.get("children", [])
    for i, child in enumerate(children):
        is_last = (i == len(children) - 1)
        connector = _ELBOW if is_last else _TEE
        next_prefix = child_prefix + (_SPACE if is_last else _PIPE)
        _render_child(child, child_prefix + connector, next_prefix, lines)


def _size_label(node: dict) -> str:
    """展示大小标签（如果开启 show_size）。"""
    ds = node.get("display_size")
    if ds:
        return f" [{ds}]"
    return ""


def _extra_label(node: dict) -> str:
    """展示额外标签，如 truncated / error。"""
    parts: list[str] = []
    if node.get("truncated"):
        parts.append(" ...")
    if node.get("error"):
        parts.append(f" [error: {node['error']}]")
    return "".join(parts)


def _match_any(name: str, patterns: list[str]) -> bool:
    """名称匹配任一 glob 模式。"""
    for pat in patterns:
        if fnmatch.fnmatch(name, pat):
            return True
    return False


# ── CLI 入口 ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    argv = sys.argv[1:]

    params: dict = {"op": "tree", "path": "."}
    i = 0
    while i < len(argv):
        a = argv[i]

        if not a.startswith("-"):
            params["path"] = a
            i += 1
            continue

        # 长选项（带 = 或独立值）
        if a.startswith("--"):
            opt = a[2:]
            if "=" in opt:
                key, val = opt.split("=", 1)
                if key == "charset":
                    pass
                else:
                    print(f"tree_ops: unknown option --{key}", file=sys.stderr)
                    sys.exit(1)
            elif opt == "noreport":
                params["noreport"] = True
            elif opt == "dirsfirst":
                pass
            elif opt == "prune":
                pass
            elif opt == "help":
                print("usage: python tree_ops.py [options] [path]", file=sys.stderr)
                print("  -a          All files (show hidden)")
                print("  -d          Directories only")
                print("  -f          Full path prefix")
                print("  -s          Show file sizes")
                print("  -h          Human-readable sizes")
                print("  -L level    Max depth")
                print("  -P pattern  Only match pattern (comma-separated)")
                print("  -I pattern  Ignore pattern (comma-separated)")
                print("  --noreport  Suppress summary")
                sys.exit(0)
            else:
                print(f"tree_ops: unknown option --{opt}", file=sys.stderr)
                sys.exit(1)
            i += 1
            continue

        # 短选项：处理 -opt 组。带值的 L/P/I 优先从下一个 argv 取值
        opts = a[1:]
        j = 0
        while j < len(opts):
            o = opts[j]
            if o == "a":
                params["all_files"] = True
            elif o == "d":
                params["dirs_only"] = True
            elif o == "f":
                params["full_path"] = True
            elif o == "s":
                params["show_size"] = True
            elif o == "h":
                params["human_size"] = True
                params["show_size"] = True
            elif o in ("L", "P", "I"):
                # 优先取当前 opts 组剩余（如 -L2）
                if j + 1 < len(opts):
                    val = opts[j + 1:]
                else:
                    # 独立参数（如 -L 2）
                    i += 1
                    if i < len(argv):
                        val = argv[i]
                    else:
                        print(f"tree_ops: -{o} requires an argument", file=sys.stderr)
                        sys.exit(1)
                if o == "L":
                    params["max_depth"] = int(val)
                elif o == "P":
                    params["pattern"] = val
                else:  # I
                    params["ignore"] = val
                break  # 消费该选项组剩余（如有）
            else:
                print(f"tree_ops: unknown option -{o}", file=sys.stderr)
                sys.exit(1)
            j += 1
        i += 1

    skill = TreeOps()
    result = skill.execute(params)
    if result["ok"]:
        print(result["result"])
    else:
        print(f"tree_ops: {result['error']}", file=sys.stderr)
        sys.exit(1)