"""M7 — Per-chat conversation cache (memory hot + JSONL file cold).

Design ref: docs/telegram_bot_design.md §4.2
Implementation plan: docs/telegram_bot_implementation_plan.md Phase 1.2
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path


class ChatCache:
    """Per-chat 对话缓存:内存 hot + 文件 cold(append-only)。"""

    def __init__(
        self,
        base_dir: str = "memories/telegram_sessions",
        hot_size: int = 20,
        ttl_minutes: int = 30,
    ) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._hot: dict[int, list[dict]] = {}
        self._hot_size = hot_size
        self._ttl = ttl_minutes * 60
        self._locks: dict[int, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def append(
        self,
        chat_id: int,
        role: str,
        content: str,
        msg_type: str = "TEXT",
        ok: bool = True,
    ) -> None:
        """追加消息:写文件 + 更新内存 hot cache。"""
        entry = {
            "ts": time.time(),
            "role": role,
            "content": content,
            "msg_type": msg_type,
            "ok": ok,
        }
        path = self._base / str(chat_id) / "chat.jsonl"
        with self._file_lock(chat_id):
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        hot = self._hot.setdefault(chat_id, [])
        hot.append(entry)
        if len(hot) > self._hot_size:
            hot.pop(0)

    def get_context(self, chat_id: int, limit: int = 20) -> list[dict]:
        """返回最近 N 条消息:优先内存,miss 时从文件尾读。"""
        if chat_id in self._hot:
            return self._hot[chat_id][-limit:]
        return self._read_tail(chat_id, limit)

    def clear(self, chat_id: int) -> None:
        """写分隔符,不删文件(可审计)。"""
        sep_entry = {
            "ts": time.time(),
            "role": "system",
            "content": f"--- cleared at {time.time()} ---",
        }
        path = self._base / str(chat_id) / "chat.jsonl"
        with self._file_lock(chat_id):
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(sep_entry, ensure_ascii=False) + "\n")
        self._hot.pop(chat_id, None)

    def _read_tail(self, chat_id: int, limit: int) -> list[dict]:
        """用 deque(maxlen=limit) 从文件尾读,跳过 clear() 写的分隔行。"""
        path = self._base / str(chat_id) / "chat.jsonl"
        if not path.exists():
            return []
        buf: deque[dict] = deque(maxlen=limit)
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("---"):
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Skip separator entries written by clear() (role=system + "---" content)
                if entry.get("role") == "system" and str(entry.get("content", "")).startswith("---"):
                    continue
                buf.append(entry)
        result = list(buf)
        self._hot[chat_id] = result[-self._hot_size:]
        return result

    def _file_lock(self, chat_id: int) -> threading.Lock:
        with self._locks_guard:
            if chat_id not in self._locks:
                self._locks[chat_id] = threading.Lock()
            return self._locks[chat_id]
