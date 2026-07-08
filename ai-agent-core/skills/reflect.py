"""Phase 6: ReflectSkill — practice feedback re-wires old notes.

Usage (via agent):
    reflect <path> --insight "..."    Append ## 实践复盘 section to old note
    reflect <path>                    Prompt for insight interactively (LLM fallback)

Behavior:
    1. Read note, parse existing frontmatter revisions
    2. Check idempotency: same insight text within 24h → skip
    3. Update frontmatter `revisions: [{date, insight, source_event}]`
    4. Append `## 实践复盘 YYYY-MM-DD` + insight block at file end
    5. File modification triggers watcher → FTS5 + graph_index re-index

Environment:
    REFLECT_DEDUP_WINDOW_HOURS: dedup window in hours (default 24)
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from skills.base import err, ok

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
# Matches "reflect <path> [--insight <text>] [--source <event>]"
_CMD_RE = re.compile(
    r"^reflect\s+(?P<path>\S+?)(?:\s+--insight\s+(?P<insight>.+?))?(?:\s+--source\s+(?P<source>.+?))?$",
    re.DOTALL,
)


class ReflectSkill:
    """Phase 6: Appends practice-review sections to old notes.

    The skill modifies the note file in-place; the background watcher picks up
    the on_modified event and re-indexes automatically.
    """

    def __init__(self, root_dir: str | None = None):
        self._root = Path(root_dir or os.environ.get("CORPUS_DIR", "rag/corpus")).resolve()
        self._dedup_hours = float(os.environ.get("REFLECT_DEDUP_WINDOW_HOURS", "24"))

    def execute(self, args: dict) -> dict:
        raw = args.get("raw_query", args.get("query", ""))

        # Try structured parse first
        m = _CMD_RE.match(raw.strip())
        if m and m.group("path"):
            file_path = m.group("path")
            insight = (m.group("insight") or "").strip()
            source = (m.group("source") or "").strip()
        else:
            # Fallback: parse from args dict
            file_path = args.get("path", "")
            insight = args.get("insight", "")
            source = args.get("source", "")
            if not file_path and "path" not in args:
                return err("reflect requires <path>, e.g. 'reflect rag/corpus/foo.md --insight \"...\"'")

        if not file_path:
            return err("reflect requires a file path argument")

        full_path = self._resolve_path(file_path)
        if not full_path or not full_path.exists():
            return err(f"file not found: {file_path}")

        if insight:
            return self._do_reflect(full_path, insight, source)

        # No insight provided — return file info for LLM to suggest one
        info = self._read_note_info(full_path)
        return ok({
            "action": "await_insight",
            "path": str(full_path),
            "title": info["title"],
            "l1": info["l1"],
            "l2": info["l2"],
            "l3": info["l3"],
            "last_revised": info["last_revised"],
            "revision_count": info["revision_count"],
            "hint": "Provide insight and re-run: reflect <path> --insight \"your insight here\"",
        })

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _resolve_path(self, raw: str) -> Path | None:
        """Resolve a path string: absolute path, relative to cwd, or short name under corpus."""
        p = Path(raw)
        if p.exists():
            return p.resolve()
        # Try under root corpus dir
        cand = self._root / raw
        if cand.exists():
            return cand
        # Try glob under root (match filename only)
        matches = list(self._root.rglob(raw))
        if len(matches) == 1:
            return matches[0]
        if matches:
            # Ambiguous — return first match but note it
            return matches[0]
        return None

    def _read_note_info(self, path: Path) -> dict[str, Any]:
        """Read frontmatter metadata from a note without parsing full content."""
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return {"title": "", "l1": "", "l2": "", "l3": "", "last_revised": "", "revision_count": 0}

        title = ""
        title_m = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
        if title_m:
            title = title_m.group(1).strip()

        fm = self._parse_frontmatter(raw)
        revisions = fm.get("revisions", [])
        last_revised = revisions[-1]["date"] if revisions else ""
        return {
            "title": title,
            "l1": fm.get("l1", ""),
            "l2": fm.get("l2", ""),
            "l3": fm.get("l3", ""),
            "last_revised": last_revised,
            "revision_count": len(revisions),
        }

    def _do_reflect(self, path: Path, insight: str, source_event: str) -> dict:
        """Core reflect logic: check dedup, update frontmatter, append section."""
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return err(f"read failed: {type(e).__name__}: {e}")

        fm_text = ""
        fm = {}
        content_body = raw
        m = _FRONTMATTER_RE.match(raw)
        if m:
            fm_text = m.group(1)
            try:
                fm = yaml.safe_load(fm_text) or {}
                if not isinstance(fm, dict):
                    fm = {}
            except yaml.YAMLError:
                fm = {}
            content_body = raw[m.end():]

        # --- dedup check ---
        if self._is_duplicate(fm, insight):
            return ok({
                "action": "skipped",
                "reason": "duplicate — same insight within dedup window",
                "path": str(path),
                "dedup_hours": self._dedup_hours,
            })

        # --- update frontmatter revisions ---
        revisions: list[dict] = list(fm.get("revisions", [])) if isinstance(fm.get("revisions"), list) else []
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        revision = {
            "date": now_iso,
            "insight": insight,
        }
        if source_event:
            revision["source_event"] = source_event
        revisions.append(revision)
        fm["revisions"] = revisions

        fm_yaml = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
        new_header = f"---\n{fm_yaml}\n---\n"

        # --- append ## 实践复盘 section ---
        today = datetime.now().strftime("%Y-%m-%d")
        section = f"\n\n## 实践复盘 {today}\n\n> insight: {insight}\n\n{insight}\n"

        new_content = new_header + content_body + section

        # Atomic write (rename avoids truncation on crash)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(new_content, encoding="utf-8")
            os.replace(tmp, path)
        except OSError as e:
            return err(f"write failed: {e}")

        # Confirm: watcher will pick up on_modified and re-index
        return ok({
            "action": "appended",
            "path": str(path),
            "date": today,
            "revision_index": len(revisions) - 1,
            "total_revisions": len(revisions),
            "note": "File updated; watcher will re-index FTS5 + graph_index automatically.",
        })

    def _is_duplicate(self, frontmatter: dict, insight: str) -> bool:
        """Check if the same insight was appended within dedup window."""
        revisions = frontmatter.get("revisions", [])
        if not isinstance(revisions, list) or not revisions:
            return False

        insight_hash = _hash_text(insight)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self._dedup_hours)

        for rev in reversed(revisions):
            if not isinstance(rev, dict):
                continue
            try:
                date_str = rev.get("date", "")
                if date_str:
                    # Various ISO formats
                    dt = _parse_iso(date_str)
                    if dt < cutoff:
                        break  # no need to check older entries
                existing = rev.get("insight", "")
                if existing and _hash_text(existing) == insight_hash:
                    return True
            except (ValueError, TypeError):
                pass
        return False

    @staticmethod
    def _parse_frontmatter(raw: str) -> dict[str, Any]:
        m = _FRONTMATTER_RE.match(raw)
        if not m:
            return {}
        try:
            fm = yaml.safe_load(m.group(1))
            return fm if isinstance(fm, dict) else {}
        except yaml.YAMLError:
            return {}


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _hash_text(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _parse_iso(s: str) -> datetime:
    """Parse an ISO-ish date string into a UTC datetime."""
    s = s.replace("Z", "+00:00")
    if "T" in s:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
