"""Read-only SessionState accessor for worker subprocesses.

Workers occasionally need session metadata (e.g. ``created_at`` to
decide whether a session is stale, or ``pending_action`` to resume an
interactive flow). The parent owns the write path; workers only read.

If ``session.json`` is corrupted or missing, we return ``None`` and let
the caller decide on a fallback (typically: treat as fresh session).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_BASE_DIR = "memories/telegram_sessions"


def _session_file(base_dir: str, chat_id: int) -> Path:
    return Path(base_dir) / str(chat_id) / "session.json"


def read_state(chat_id: int, base_dir: str = DEFAULT_BASE_DIR) -> dict[str, Any] | None:
    """Return the session state dict, or ``None`` if unavailable.

    Returns ``None`` (not raises) on missing file, parse error, or
    permission error — workers should degrade gracefully.
    """
    path = _session_file(base_dir, chat_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def read_pending_action(chat_id: int, base_dir: str = DEFAULT_BASE_DIR) -> dict[str, Any] | None:
    """Convenience accessor for the pending_action sub-document."""
    state = read_state(chat_id, base_dir)
    if state is None:
        return None
    pending = state.get("pending_action")
    return pending if isinstance(pending, dict) else None
