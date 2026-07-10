"""Read-only ChatCache accessor for worker subprocesses.

Workers need recent conversation history for context (e.g. to resolve
"yes"/"no" answers, or to include prior turns in an LLM prompt). The
parent owns the write path (append-only JSONL); workers only read.

This module deliberately does NOT expose any write API — workers must
not mutate conversation history. Results are returned as plain dicts to
avoid coupling to the parent's Message dataclass.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_BASE_DIR = "memories/telegram_sessions"


def _chat_jsonl_path(base_dir: str, chat_id: int) -> Path:
    return Path(base_dir) / str(chat_id) / "chat.jsonl"


def read_recent(chat_id: int, limit: int = 20, base_dir: str = DEFAULT_BASE_DIR) -> list[dict[str, Any]]:
    """Return the last ``limit`` messages for a chat, oldest-first.

    Returns an empty list if the chat file does not exist or is empty.
    Malformed lines are skipped (append-only JSONL tolerates partial
    writes from crashes).
    """
    path = _chat_jsonl_path(base_dir, chat_id)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def count_messages(chat_id: int, base_dir: str = DEFAULT_BASE_DIR) -> int:
    """Return the total number of persisted messages for a chat."""
    path = _chat_jsonl_path(base_dir, chat_id)
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
