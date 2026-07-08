"""Pipeline worker — clean → classify → frontmatter → FTS5 upsert → index.yaml upsert.

Triggered by background_worker.py on file create/modify, or runnable directly:
    python -m scripts.pipeline_worker --path rag/corpus/foo.md

Returns standard envelope {"ok": bool, "result": ..., "error": str | None}.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from rag.fts_index import FtsIndex
from rag.graph_index import GraphIndex
from rag.chunker import TextChunker


_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
_DEFAULT_RULES_PATH = _PROJECT_ROOT / "config" / "tag_rules.yaml"
_DEFAULT_INDEX_YAML = _PROJECT_ROOT / "config" / "index.yaml"
_DEFAULT_FTS_PATH = _PROJECT_ROOT / "rag" / "fts_index.db"
_DEFAULT_GRAPH_DB_PATH = _PROJECT_ROOT / "rag" / "graph_index.db"

# Module-level lock — retained for backward compat with index_yaml_upsert callers.
# New graph_index_upsert path uses SQLite WAL and does not need this lock.
_INDEX_YAML_LOCK = threading.Lock()

_CODEBLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_TRAILING_WS_RE = re.compile(r"[ \t]+\n")
_MULTIBLANK_RE = re.compile(r"\n{3,}")
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
# Phase 4: [[wikilink]] syntax for knowledge_edges
_WIKILINK_RE = re.compile(r"\[\[([^\]]+?)\]\]")


# ---------------------------------------------------------------------------
# 1. clean_md
# ---------------------------------------------------------------------------

def clean_md(text: str, max_chars: int = 100_000,
             keep_codeblocks_stashed: bool = False) -> str:
    """Strip HTML remnants, collapse whitespace, cap length.

    Code blocks (```...```) are protected from HTML stripping.
    Phase 4: 若 keep_codeblocks_stashed=True，返回时代码块仍为 \\x00CODEBLOCK{n}\\x00
    占位符（不恢复），用于 wikilink 提取时跳过代码块内的 [[...]]。
    """
    if not text:
        return ""

    # Strip <script>/<style>/<noscript> blocks.
    text = _SCRIPT_STYLE_RE.sub("", text)

    # Protect code blocks while we strip inline HTML tags.
    code_blocks: list[str] = []
    def _stash(m: re.Match) -> str:
        code_blocks.append(m.group(0))
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"
    text = _CODEBLOCK_RE.sub(_stash, text)

    # Strip remaining HTML tags.
    text = _HTML_TAG_RE.sub("", text)

    # Restore code blocks UNLESS caller wants them stashed (for wikilink extraction).
    if not keep_codeblocks_stashed:
        for i, block in enumerate(code_blocks):
            text = text.replace(f"\x00CODEBLOCK{i}\x00", block)

    # Whitespace normalization.
    text = _TRAILING_WS_RE.sub("\n", text)
    text = _MULTIBLANK_RE.sub("\n\n", text)

    # Length cap — cut at nearest paragraph boundary <= max_chars.
    if len(text) > max_chars:
        cut = text.rfind("\n\n", 0, max_chars)
        if cut == -1 or cut < max_chars // 2:
            cut = max_chars
        text = text[:cut].rstrip() + "\n\n[...truncated...]"

    return text.strip() + "\n"


# ---------------------------------------------------------------------------
# 2. classify
# ---------------------------------------------------------------------------

def _load_rules(rules_path: Path) -> dict[str, Any]:
    if not rules_path.exists():
        return {"defaults": {"l1": "未分类", "l2": "Misc", "l3": "General"}, "rules": []}
    with rules_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def classify(
    title: str,
    content: str,
    rules: dict[str, Any],
) -> tuple[str, str, str]:
    """Return (l1, l2, l3) by scanning title + first 5000 chars of content.

    First matching rule (top-to-bottom) wins. Falls back to defaults.
    """
    defaults = rules.get("defaults") or {"l1": "未分类", "l2": "Misc", "l3": "General"}
    haystack = f"{title} {content[:5000]}".lower()
    if not haystack.strip():
        return (defaults["l1"], defaults["l2"], defaults["l3"])

    for rule in rules.get("rules", []):
        keywords = rule.get("keywords") or []
        if any(kw.lower() in haystack for kw in keywords):
            return (rule["l1"], rule["l2"], rule["l3"])

    return (defaults["l1"], defaults["l2"], defaults["l3"])


def classify_multi(
    title: str,
    content: str,
    rules: dict[str, Any],
    max_labels: int = 3,
) -> list[tuple[str, str, str, float]]:
    """Phase 4: Return top-N classification labels with frequency-weighted scores.

    Each keyword hit counts as +1 score toward its rule. Returns sorted
    (l1, l2, l3, score) descending, capped at max_labels.
    """
    defaults = rules.get("defaults") or {"l1": "未分类", "l2": "Misc", "l3": "General"}
    haystack = f"{title} {content[:5000]}".lower()
    if not haystack.strip():
        return [(defaults["l1"], defaults["l2"], defaults["l3"], 1.0)]

    scores: dict[tuple[str, str, str], float] = {}
    for rule in rules.get("rules", []):
        keywords = rule.get("keywords") or []
        hits = sum(1 for kw in keywords if kw.lower() in haystack)
        if hits > 0:
            key = (rule["l1"], rule["l2"], rule["l3"])
            scores[key] = scores.get(key, 0) + hits

    if not scores:
        return [(defaults["l1"], defaults["l2"], defaults["l3"], 1.0)]

    # Normalize scores
    total = sum(scores.values())
    result = [(l1, l2, l3, s / total) for (l1, l2, l3), s in scores.items()]
    result.sort(key=lambda x: x[3], reverse=True)
    return result[:max_labels]


# ---------------------------------------------------------------------------
# 3. inject_frontmatter
# ---------------------------------------------------------------------------

def _extract_title(text: str) -> str:
    m = _TITLE_RE.search(text)
    if m:
        return m.group(1).strip()
    return ""


def inject_frontmatter(
    path: Path,
    l1: str,
    l2: str,
    l3: str,
    categories: list[tuple[str, str, str]] | None = None,
) -> bool:
    """Inject YAML frontmatter at top of file if missing.

    Phase 4: 若提供 categories（多标签），写入 `categories` 数组字段；
    否则仅写单一 l1/l2/l3（向后兼容）。

    Returns True if file was modified, False if frontmatter already present
    (with l1/l2/l3 fields).
    """
    raw = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(raw)
    if m:
        existing = yaml.safe_load(m.group(1)) or {}
        if all(k in existing for k in ("l1", "l2", "l3")):
            return False

    title = _extract_title(raw)
    fetched_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    fm: dict[str, Any] = {
        "l1": l1,
        "l2": l2,
        "l3": l3,
        "title": title,
        "fetched_at": fetched_at,
    }
    if categories and len(categories) > 1:
        fm["categories"] = [
            {"l1": c[0], "l2": c[1], "l3": c[2]} for c in categories
        ]
    fm_yaml = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    new_text = f"---\n{fm_yaml}\n---\n\n{raw}"

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, path)
    return True


# ---------------------------------------------------------------------------
# 4. fts5_upsert
# ---------------------------------------------------------------------------

def fts5_upsert(
    fts: FtsIndex,
    path: str,
    title: str,
    l1: str,
    l2: str,
    l3: str,
    content: str,
) -> None:
    category = f"{l1}/{l2}/{l3}"
    fts.upsert(path=path, title=title or "", category=category, content=content)


# ---------------------------------------------------------------------------
# 5. index_yaml_upsert
# ---------------------------------------------------------------------------

def _backup_and_reset(yaml_path: Path) -> dict:
    """If index.yaml is corrupt, back it up and start fresh."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = yaml_path.with_suffix(f".yaml.bak.{ts}")
    try:
        os.replace(yaml_path, bak)
    except OSError:
        pass
    return {"version": 1, "tree": {}}


def _atomic_write_yaml(yaml_path: Path, data: dict) -> None:
    tmp = yaml_path.with_suffix(yaml_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, yaml_path)


def index_yaml_upsert(
    yaml_path: Path,
    doc_path: str,
    l1: str,
    l2: str,
    l3: str,
    lock: threading.Lock | None = None,
) -> bool:
    """Append doc_path as L4 leaf under tree[l1][l2][l3]. Idempotent on path.

    Returns True if a new entry was added, False if path was already present.
    """
    lock = lock or _INDEX_YAML_LOCK
    with lock:
        if not yaml_path.exists():
            data: dict[str, Any] = {"version": 1, "tree": {}}
        else:
            try:
                with yaml_path.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {"version": 1, "tree": {}}
                if "tree" not in data:
                    data["tree"] = {}
            except yaml.YAMLError:
                data = _backup_and_reset(yaml_path)

        tree = data["tree"]
        tree.setdefault(l1, {})
        tree[l1].setdefault(l2, {})
        tree[l1][l2].setdefault(l3, [])

        leaves = tree[l1][l2][l3]
        if any(isinstance(x, dict) and x.get("path") == doc_path for x in leaves):
            return False

        leaves.append({
            "path": doc_path,
            "added_at": datetime.now().isoformat(),
            "level": "L4",
        })
        _atomic_write_yaml(yaml_path, data)
        return True


# ---------------------------------------------------------------------------
# 5b. graph_index_upsert — SQLite-backed L1/L2/L3/L4 graph (Phase 2)
# ---------------------------------------------------------------------------

def graph_index_upsert(
    graph_db_path: Path,
    doc_path: str,
    l1: str,
    l2: str,
    l3: str,
) -> bool:
    """Insert/update doc as L4 leaf in SQLite document_graph. Idempotent on path.

    Returns True if new row inserted, False if path already existed.
    Uses SQLite WAL — no application-level lock needed for concurrent writers.
    """
    gi = GraphIndex(str(graph_db_path))
    try:
        return gi.upsert(path=doc_path, l1=l1, l2=l2, l3=l3)
    finally:
        gi.close()


def graph_index_upsert_categories(
    graph_db_path: Path,
    doc_path: str,
    categories: list[tuple[str, str, str]],
) -> list[bool]:
    """Phase 4: Multi-homing upsert — write multiple (l1,l2,l3) for one doc."""
    gi = GraphIndex(str(graph_db_path))
    try:
        return gi.upsert_categories(doc_path, categories)
    finally:
        gi.close()


# ---------------------------------------------------------------------------
# Phase 4: wikilink parsing + knowledge_edges upsert
# ---------------------------------------------------------------------------

def extract_wikilinks(text: str) -> list[str]:
    """Parse [[wikilink]] syntax from Markdown text.

    Returns list of target names (raw strings inside [[ ]]).
    Supports [[Title]], [[path/to/file.md]], [[display|target]] (returns target).
    """
    results: list[str] = []
    for m in _WIKILINK_RE.finditer(text):
        inner = m.group(1).strip()
        if "|" in inner:
            inner = inner.split("|", 1)[1].strip()
        if inner:
            results.append(inner)
    return results


def upsert_edges_from_wikilinks(
    graph_db_path: Path,
    source_path: str,
    text: str,
    corpus_dir: Path | None = None,
    rel_type: str = "wikilink",
) -> int:
    """Phase 4: Parse [[wikilinks]] from text, resolve to actual file paths,
    and upsert knowledge_edges.

    Args:
        source_path: absolute path of the source doc.
        text: doc content (post-clean_md).
        corpus_dir: rag/corpus/ root for resolving wikilink targets by basename.
        rel_type: edge relationship type (default 'wikilink').

    Returns: number of edges upserted.
    """
    targets = extract_wikilinks(text)
    if not targets:
        return 0

    # Build basename → absolute path index (lazy, only if targets exist)
    target_paths: dict[str, str] = {}
    if corpus_dir is not None:
        corpus_dir = Path(corpus_dir).resolve()
        for p in corpus_dir.rglob("*.md"):
            target_paths[p.name] = str(p)
            target_paths[p.stem] = str(p)  # also index by stem (without .md)

    gi = GraphIndex(str(graph_db_path))
    n = 0
    try:
        for tgt in targets:
            # Resolve target: try direct, then by basename, then by stem
            tgt_path: str | None = None
            if corpus_dir is not None:
                if tgt in target_paths:
                    tgt_path = target_paths[tgt]
                elif tgt.endswith(".md") and (corpus_dir / tgt).exists():
                    tgt_path = str((corpus_dir / tgt).resolve())
                else:
                    candidate = corpus_dir / tgt
                    if candidate.exists():
                        tgt_path = str(candidate.resolve())
            else:
                tgt_path = tgt  # raw, no resolution

            if tgt_path and tgt_path != source_path:
                if gi.upsert_edge(source_path, tgt_path, weight=1.0, rel_type=rel_type):
                    n += 1
    finally:
        gi.close()
    return n


def graph_index_update(
    graph_db_path: Path,
    doc_path: str,
    l1: str,
    l2: str,
    l3: str,
) -> bool:
    """Like graph_index_upsert but alias for external use (e.g. chunk indexing)."""
    return graph_index_upsert(graph_db_path, doc_path, l1, l2, l3)


def graph_index_delete(graph_db_path: Path, doc_path: str) -> int:
    """Delete a doc from document_graph by path. Returns rows deleted."""
    gi = GraphIndex(str(graph_db_path))
    try:
        return gi.delete(doc_path)
    finally:
        gi.close()


# ---------------------------------------------------------------------------
# 5c. L5 chunk-level index (Phase 7)
# ---------------------------------------------------------------------------

def chunk_index_upsert(
    graph_db_path: Path,
    doc_path: str,
    l1: str,
    l2: str,
    l3: str,
    chunks: list[tuple[str, str]],
) -> int:
    """Upsert chunks for a parent document in document_chunks table.

    Returns number of chunks inserted.
    """
    gi = GraphIndex(str(graph_db_path))
    try:
        return gi.upsert_chunks(
            parent_path=doc_path, l1=l1, l2=l2, l3=l3, chunks=chunks,
        )
    finally:
        gi.close()


def chunk_index_delete(graph_db_path: Path, doc_path: str) -> int:
    """Delete all chunks for a parent document."""
    gi = GraphIndex(str(graph_db_path))
    try:
        return gi.delete_chunks(parent_path=doc_path)
    finally:
        gi.close()


def delete_file_indexes(
    path: Path,
    fts_path: Path | None = None,
    graph_db_path: Path | None = None,
) -> dict:
    """Phase 3: 清理已删除文件的所有索引残留（含 Phase 7 chunks）。

    Returns envelope {"ok": bool, "result": {"fts_deleted": int, "graph_deleted": int, "chunks_deleted": int}, "error": str|None}.
    文件本身已不存在不算错误（这正是本函数的预期调用场景）。
    """
    fts_path = fts_path or _DEFAULT_FTS_PATH
    graph_db_path = graph_db_path or _DEFAULT_GRAPH_DB_PATH
    abs_path = str(Path(path).resolve())

    fts_deleted = 0
    try:
        from rag.fts_index import FtsIndex
        fts = FtsIndex(str(fts_path))
        try:
            fts_deleted = fts.delete(abs_path)
        finally:
            fts.close()
    except sqlite3.Error as e:
        return {"ok": False, "result": None, "error": f"fts5 delete failed: {e}"}

    graph_deleted = 0
    chunks_deleted = 0
    try:
        graph_deleted = graph_index_delete(graph_db_path, abs_path)
        chunks_deleted = chunk_index_delete(graph_db_path, abs_path)
    except sqlite3.Error as e:
        return {"ok": False, "result": None, "error": f"graph_index delete failed: {e}"}

    return {
        "ok": True,
        "result": {
            "path": abs_path,
            "fts_deleted": fts_deleted,
            "graph_deleted": graph_deleted,
            "chunks_deleted": chunks_deleted,
        },
        "error": None,
    }


# ---------------------------------------------------------------------------
# 5c. index_yaml_export — export SQLite graph back to config/index.yaml (read-only snapshot)
# ---------------------------------------------------------------------------

def export_graph_to_yaml(graph_db_path: Path, yaml_path: Path) -> int:
    """Export SQLite document_graph → config/index.yaml (single-shot, read-only).

    Useful for human inspection / git diff. The yaml file is no longer the
    source of truth — it's a derived snapshot.
    Returns number of docs exported.
    """
    gi = GraphIndex(str(graph_db_path))
    try:
        data = gi.export_yaml_dict()
        count = gi.count()
    finally:
        gi.close()
    tmp = yaml_path.with_suffix(yaml_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write("# Auto-exported from rag/graph_index.db (SQLite document_graph).\n")
        f.write("# This file is a read-only snapshot — DO NOT edit. Source of truth is SQLite.\n")
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, yaml_path)
    return count


# ---------------------------------------------------------------------------
# process_file — full pipeline
# ---------------------------------------------------------------------------

def process_file(
    path: Path,
    rules_path: Path | None = None,
    index_yaml_path: Path | None = None,
    fts_path: Path | None = None,
    graph_db_path: Path | None = None,
) -> dict:
    """Run the full ingestion pipeline on a single .md file.

    Returns envelope {"ok": bool, "result": {...}, "error": str | None}.

    Phase 2: graph index now writes to SQLite (rag/graph_index.db) instead of
    config/index.yaml. The yaml file becomes a read-only export snapshot.

    Phase 7: L5 chunk-level atomic index + offline LLM classification hook.
    """
    import os as _os

    path = Path(path)
    rules_path = rules_path or _DEFAULT_RULES_PATH
    index_yaml_path = index_yaml_path or _DEFAULT_INDEX_YAML
    fts_path = fts_path or _DEFAULT_FTS_PATH
    graph_db_path = graph_db_path or _DEFAULT_GRAPH_DB_PATH

    if not path.exists():
        return {"ok": False, "result": None, "error": f"file not found: {path}"}
    if path.suffix.lower() != ".md":
        return {"ok": False, "result": None, "error": f"not a markdown file: {path}"}

    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return {"ok": False, "result": None, "error": f"read failed: {type(e).__name__}: {e}"}

    cleaned = clean_md(raw)
    rules = _load_rules(rules_path)
    title = _extract_title(raw)
    l1, l2, l3 = classify(title, cleaned, rules)

    # Phase 7: External classifier hook (Ollama offline small model) — optional
    try:
        from scripts.offline_classifier import classify_hook
        l1, l2, l3 = classify_hook(title, cleaned, (l1, l2, l3))
    except ImportError:
        pass  # no offline classifier installed

    # Phase 4: multi-label classification (top-3 by keyword frequency)
    multi_labels = classify_multi(title, cleaned, rules, max_labels=3)
    primary = multi_labels[0]
    l1, l2, l3 = primary[0], primary[1], primary[2]
    categories = [(c[0], c[1], c[2]) for c in multi_labels]

    # Frontmatter injection (may rewrite file — watcher debounce will swallow
    # the resulting on_modified event).
    try:
        inject_frontmatter(path, l1, l2, l3, categories=categories)
    except OSError as e:
        return {"ok": False, "result": None, "error": f"frontmatter inject failed: {e}"}

    # FTS5 upsert.
    try:
        fts = FtsIndex(str(fts_path))
        try:
            fts5_upsert(fts, str(path), title, l1, l2, l3, cleaned)
        finally:
            fts.close()
    except sqlite3.Error as e:
        return {"ok": False, "result": None, "error": f"fts5 upsert failed: {e}"}

    # Phase 4: Graph index multi-homing upsert (all categories).
    graph_added_flags: list[bool] = []
    try:
        graph_added_flags = graph_index_upsert_categories(
            graph_db_path, str(path), categories,
        )
    except sqlite3.Error as e:
        return {"ok": False, "result": None, "error": f"graph_index upsert failed: {e}"}
    graph_added = graph_added_flags[0] if graph_added_flags else False

    # Phase 4: Parse [[wikilinks]] and upsert knowledge_edges.
    # Use stashed text so wikilinks inside code blocks (\x00CODEBLOCK{n}\x00)
    # don't get parsed.
    edges_added = 0
    try:
        corpus_dir = Path(path).parent
        cleaned_stashed = clean_md(raw, keep_codeblocks_stashed=True)
        edges_added = upsert_edges_from_wikilinks(
            graph_db_path, str(path), cleaned_stashed, corpus_dir=corpus_dir,
        )
    except sqlite3.Error:
        pass  # edges failure is non-fatal

    # Phase 7: L5 chunk-level atomic index
    chunk_count = 0
    chunk_enabled = _os.environ.get("PIPELINE_CHUNK_ENABLED", "1").lower() in ("1", "true", "yes")
    if chunk_enabled:
        try:
            chunk_size = int(_os.environ.get("PIPELINE_CHUNK_SIZE", "1200"))
            chunk_overlap = int(_os.environ.get("PIPELINE_CHUNK_OVERLAP", "150"))
            chunker = TextChunker(
                strategy="paragraph", max_chars=chunk_size, overlap_chars=chunk_overlap,
            )
            chunks = chunker.chunk(str(path), cleaned)
            if chunks:
                chunk_count = chunk_index_upsert(
                    graph_db_path, str(path), l1, l2, l3, chunks,
                )
        except (sqlite3.Error, ValueError) as e:
            # Non-fatal: main pipeline already succeeded
            import logging
            logging.getLogger("pipeline").warning("chunk index failed for %s: %s", path, e)

    # 保留旧字段 index_yaml_added 以向后兼容（实际为 graph_added）
    return {
        "ok": True,
        "result": {
            "path": str(path),
            "title": title,
            "l1": l1,
            "l2": l2,
            "l3": l3,
            "category": f"{l1}/{l2}/{l3}",
            "categories": [{"l1": c[0], "l2": c[1], "l3": c[2]} for c in categories],
            "index_yaml_added": graph_added,
            "graph_added": graph_added,
            "edges_added": edges_added,
            "chars": len(cleaned),
            "chunk_count": chunk_count,
        },
        "error": None,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Run ingestion pipeline on a .md file")
    parser.add_argument("--path", required=True, help="Path to markdown file")
    parser.add_argument("--rules", default=str(_DEFAULT_RULES_PATH))
    parser.add_argument("--index-yaml", default=str(_DEFAULT_INDEX_YAML))
    parser.add_argument("--fts-db", default=str(_DEFAULT_FTS_PATH))
    parser.add_argument("--graph-db", default=str(_DEFAULT_GRAPH_DB_PATH))
    args = parser.parse_args()

    out = process_file(
        Path(args.path),
        rules_path=Path(args.rules),
        index_yaml_path=Path(args.index_yaml),
        fts_path=Path(args.fts_db),
        graph_db_path=Path(args.graph_db),
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
