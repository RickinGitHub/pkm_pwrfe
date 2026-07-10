"""IPC serialization for IncomingMessage across the subprocess boundary.

The parent (main bot) builds an :class:`IncomingMessage` and passes it
to a worker subprocess as a JSON dict. The worker reconstructs a
read-only view via :func:`from_ipc_dict`. We do NOT import the full
IncomingMessage class here to keep workers decoupled from the parent's
internal class hierarchy.

The wire format is intentionally flat — nested objects (``raw``) are
serialized as-is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IpcMessage:
    """Read-only view of an IncomingMessage inside a worker."""

    chat_id: int
    user_id: int
    msg_type: str  # MsgType.value
    text: str
    raw: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
    callback_data: str | None = None
    category: str = "INSTANT"  # ProcessCategory.value

    def to_ipc_dict(self) -> dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "msg_type": self.msg_type,
            "text": self.text,
            "raw": self.raw,
            "timestamp": self.timestamp,
            "callback_data": self.callback_data,
            "category": self.category,
        }


def from_ipc_dict(data: dict[str, Any]) -> IpcMessage:
    """Reconstruct an IpcMessage from a JSON-decoded dict.

    Unknown keys are ignored for forward compatibility — if the parent
    adds new fields, old workers still run.
    """
    return IpcMessage(
        chat_id=int(data.get("chat_id", 0)),
        user_id=int(data.get("user_id", 0)),
        msg_type=str(data.get("msg_type", "TEXT")),
        text=str(data.get("text", "")),
        raw=dict(data.get("raw", {}) or {}),
        timestamp=float(data.get("timestamp", 0.0)),
        callback_data=data.get("callback_data"),
        category=str(data.get("category", "INSTANT")),
    )
