"""M3 — Message types and classification (MsgType + ProcessCategory + IncomingMessage).

Design ref: docs/telegram_bot_design.md §4.4
Implementation plan: docs/telegram_bot_implementation_plan.md Phase 1.1
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class MsgType(Enum):
    """消息来源形态:描述消息是怎么进来的,不描述怎么执行。"""
    COMMAND = auto()
    TEXT = auto()
    URL = auto()
    CALLBACK = auto()
    FILE = auto()


class ProcessCategory(Enum):
    """执行耗时与处理路径:INSTANT 主进程内 / LONG 派生子进程 / INTERACTIVE 等用户多轮。"""
    INSTANT = auto()
    LONG = auto()
    INTERACTIVE = auto()


_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)

_LONG_COMMANDS: frozenset[str] = frozenset({
    "/getfile", "/fetch", "/crawl", "/抓取", "/下载",
    "/build", "/rebuild", "/update",
    "/ingest", "/pipeline", "/reindex", "/unindex",
    "/review", "/evolve", "/reflect",
})

_INTERACTIVE_COMMANDS: frozenset[str] = frozenset({
    "/clear",
})


@dataclass
class IncomingMessage:
    """Telegram 入站消息的统一表示,贯穿 Dispatcher → Queue → Worker 全链路。"""

    chat_id: int
    user_id: int
    msg_type: MsgType
    text: str
    raw: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
    callback_data: str | None = None
    category: ProcessCategory = field(default=ProcessCategory.INSTANT, init=False)
    worker_result: dict[str, Any] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.category = _classify_category(self)

    @property
    def is_command(self) -> bool:
        return self.msg_type == MsgType.COMMAND

    @property
    def is_long_running(self) -> bool:
        return self.category == ProcessCategory.LONG

    @property
    def is_interactive(self) -> bool:
        return self.category == ProcessCategory.INTERACTIVE

    @property
    def query_for_agent(self) -> str:
        if self.msg_type == MsgType.COMMAND:
            return self.text[1:]
        if self.msg_type == MsgType.URL:
            return f"fetch {self.text}"
        return self.text

    def to_ipc_dict(self) -> dict[str, Any]:
        """Serialize to a flat dict for IPC with subprocess workers.

        The worker side deserializes via ``scripts.bot_workers.message_types.from_ipc_dict``.
        """
        return {
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "msg_type": self.msg_type.name,
            "text": self.text,
            "raw": self.raw,
            "timestamp": self.timestamp,
            "callback_data": self.callback_data,
            "category": self.category.name,
        }


def _classify_category(msg: IncomingMessage) -> ProcessCategory:
    """根据 MsgType + text 推导 ProcessCategory。"""
    if msg.msg_type == MsgType.FILE:
        return ProcessCategory.LONG
    if msg.msg_type == MsgType.URL:
        return ProcessCategory.LONG
    if msg.msg_type == MsgType.COMMAND:
        cmd_root = msg.text.split()[0].lower() if msg.text else ""
        if cmd_root in _LONG_COMMANDS:
            return ProcessCategory.LONG
        if cmd_root in _INTERACTIVE_COMMANDS:
            return ProcessCategory.INTERACTIVE
        return ProcessCategory.INSTANT
    return ProcessCategory.INSTANT


def classify_message(update: dict[str, Any]) -> IncomingMessage | None:
    """将 Telegram Bot API update 转为 IncomingMessage。"""
    msg = update.get("message") or update.get("callback_query", {}).get("message")
    if not msg:
        return None

    chat_id = msg["chat"]["id"]
    user_id = msg.get("from", {}).get("id", 0)
    text = msg.get("text", "")
    ts = msg.get("date", 0)

    cb = update.get("callback_query")
    if cb:
        return IncomingMessage(
            chat_id=chat_id, user_id=user_id,
            msg_type=MsgType.CALLBACK,
            text=cb.get("data", ""),
            raw=update, timestamp=ts,
            callback_data=cb.get("data"),
        )

    for file_key in ("document", "photo", "audio", "video", "voice"):
        if file_key in msg:
            return IncomingMessage(
                chat_id=chat_id, user_id=user_id,
                msg_type=MsgType.FILE,
                text=msg.get("caption", ""),
                raw=update, timestamp=ts,
            )

    if text.startswith("/"):
        return IncomingMessage(
            chat_id=chat_id, user_id=user_id,
            msg_type=MsgType.COMMAND,
            text=text, raw=update, timestamp=ts,
        )

    if _URL_RE.match(text.strip()):
        return IncomingMessage(
            chat_id=chat_id, user_id=user_id,
            msg_type=MsgType.URL,
            text=text.strip(), raw=update, timestamp=ts,
        )

    if text:
        return IncomingMessage(
            chat_id=chat_id, user_id=user_id,
            msg_type=MsgType.TEXT,
            text=text, raw=update, timestamp=ts,
        )

    return None
