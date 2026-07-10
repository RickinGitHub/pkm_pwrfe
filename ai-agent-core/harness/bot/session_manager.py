"""M6 — Per-chat session state machine (pending-action tracking, file-persisted).

Design ref: docs/telegram_bot_design.md §4.6
Implementation plan: docs/telegram_bot_implementation_plan.md Phase 1.3
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from time import time


@dataclass
class SessionState:
    """Per-chat 会话状态,持久化到 session.json。"""

    chat_id: int
    pending_action: str | None = None
    pending_data: dict | None = None
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    message_count: int = 0
    _dirty: bool = field(default=False, init=False, repr=False)

    def is_idle(self) -> bool:
        return self.pending_action is None

    def set_pending(self, action: str, data: dict) -> None:
        self.pending_action = action
        self.pending_data = data
        self.updated_at = time()
        self._dirty = True

    def clear_pending(self) -> None:
        self.pending_action = None
        self.pending_data = None
        self.updated_at = time()
        self._dirty = True

    def touch(self) -> None:
        """Mark activity (called on each message in this chat)."""
        self.updated_at = time()
        self.message_count += 1
        self._dirty = True

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_dirty", None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SessionState":
        """反序列化(忽略未知字段,前向兼容)。"""
        known = {f.name for f in cls.__dataclass_fields__.values() if f.init}
        return cls(**{k: v for k, v in d.items() if k in known})


class SessionManager:
    """Per-chat 会话状态管理器,状态落地到 session.json。"""

    def __init__(
        self,
        base_dir: str = "memories/telegram_sessions",
        ttl_minutes: int = 30,
        max_sessions: int = 200,
    ) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl_minutes * 60
        self._max = max_sessions
        self._hot: dict[int, SessionState] = {}
        self._locks: dict[int, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def _session_dir(self, chat_id: int) -> Path:
        return self._base / str(chat_id)

    def _session_file(self, chat_id: int) -> Path:
        return self._session_dir(chat_id) / "session.json"

    def _lock(self, chat_id: int) -> threading.Lock:
        with self._global_lock:
            if chat_id not in self._locks:
                self._locks[chat_id] = threading.Lock()
            return self._locks[chat_id]

    def get_or_create(self, chat_id: int) -> SessionState:
        with self._lock(chat_id):
            if chat_id in self._hot:
                state = self._hot[chat_id]
                state.updated_at = time()
                state._dirty = True
                return state
            state = self._load_from_file(chat_id)
            if state is None:
                if len(self._hot) >= self._max:
                    self._evict_expired()
                state = SessionState(chat_id=chat_id)
                self._ensure_dir(chat_id)
            self._hot[chat_id] = state
            return state

    def get(self, chat_id: int) -> SessionState | None:
        with self._lock(chat_id):
            if chat_id in self._hot:
                return self._hot[chat_id]
            return self._load_from_file(chat_id)

    def save(self, chat_id: int) -> None:
        with self._lock(chat_id):
            state = self._hot.get(chat_id)
            if state is None or not state._dirty:
                return
            self._save_unsafe(chat_id, state)
            state._dirty = False

    def clear(self, chat_id: int) -> None:
        with self._lock(chat_id):
            self._hot.pop(chat_id, None)
            f = self._session_file(chat_id)
            if f.exists():
                try:
                    f.unlink()
                except OSError:
                    pass

    def _load_from_file(self, chat_id: int) -> SessionState | None:
        f = self._session_file(chat_id)
        if not f.exists():
            return None
        try:
            return SessionState.from_dict(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, TypeError):
            return None

    def _ensure_dir(self, chat_id: int) -> None:
        self._session_dir(chat_id).mkdir(parents=True, exist_ok=True)

    def _evict_expired(self) -> None:
        now = time()
        expired = [
            cid for cid, s in self._hot.items()
            if now - s.updated_at > self._ttl
        ]
        for cid in expired:
            state = self._hot.pop(cid)
            if state._dirty:
                self._save_unsafe(cid, state)

    def _save_unsafe(self, chat_id: int, state: SessionState) -> None:
        self._ensure_dir(chat_id)
        tmp = self._session_file(chat_id).with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._session_file(chat_id))
