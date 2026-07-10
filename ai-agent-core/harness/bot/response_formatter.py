"""M5 — Communication protocol (BotResponse + ResponseFormatter).

AgentCore returns {"ok": bool, "result": Any, "error": str | None}.
This module converts that raw dict into a Telegram-sendable BotResponse.

Design ref: docs/telegram_bot_design.md §4.5
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BotResponse:
    """AgentCore 输出 → Telegram 可发送格式的适配层。"""

    text: str
    parse_mode: str = "Markdown"
    reply_markup: dict | None = None
    split_long: bool = False
    disable_notification: bool = False


class ResponseFormatter:
    """将 agent.handle() 的 raw dict 转换为 BotResponse。"""

    MAX_CHARS = 4096

    @classmethod
    def format(cls, result: dict[str, Any], msg: Any = None) -> BotResponse:
        """Main entry: raw agent result → BotResponse."""
        if not result.get("ok"):
            return cls._format_error(result.get("error", "unknown error"))

        data = result.get("result")
        if isinstance(data, (int, float)):
            return cls._format_number(data)
        if isinstance(data, list):
            return cls._format_list(data)
        if isinstance(data, dict):
            return cls._format_dict(data, msg)
        return cls._format_text(str(data) if data else "(empty)")

    @classmethod
    def _format_error(cls, error: str) -> BotResponse:
        return BotResponse(text=f"❌ `{error}`")

    @classmethod
    def _format_number(cls, n: int | float) -> BotResponse:
        return BotResponse(text=f"✅ result: `{n}`")

    @classmethod
    def _format_list(cls, items: list) -> BotResponse:
        if not items:
            return BotResponse(text="_no matches_")
        lines = [f"📄 {len(items)} matches:\n"]
        for i, item in enumerate(items[:20], 1):
            title = item.get("title", item.get("path", str(item)))[:60]
            lines.append(f"{i}. {title}")
        if len(items) > 20:
            lines.append(f"\n_...and {len(items) - 20} more_")
        return cls._maybe_split("\n".join(lines))

    @classmethod
    def _format_dict(cls, data: dict, msg: Any = None) -> BotResponse:
        # fetch 结果 → 带确认按钮
        if "filepath" in data and "sync" not in data:
            return BotResponse(
                text=cls._fetch_summary(data),
                reply_markup=cls._confirm_keyboard(f"confirm_ingest:{data['filepath']}"),
            )
        # ingest 结果
        if "total" in data and "ok" in data:
            return BotResponse(text=f"✅ Ingested: {data['ok']}/{data['total']} files")
        # 通用 dict — safe JSON truncation
        snippet = json.dumps(data, ensure_ascii=False, indent=2)[:2000]
        return cls._maybe_split(f"```json\n{snippet}\n```")

    @classmethod
    def _format_text(cls, text: str) -> BotResponse:
        return cls._maybe_split(text)

    @classmethod
    def _maybe_split(cls, text: str) -> BotResponse:
        """超 4096 字符时标记分段。"""
        if len(text) <= cls.MAX_CHARS:
            return BotResponse(text=text)
        return BotResponse(text=text, split_long=True)

    @staticmethod
    def _confirm_keyboard(callback_data: str) -> dict:
        return {
            "inline_keyboard": [[
                {"text": "📥 确认入库", "callback_data": callback_data},
                {"text": "❌ 忽略", "callback_data": "cancel"},
            ]]
        }

    @staticmethod
    def _fetch_summary(data: dict) -> str:
        title = data.get("title", "")[:40]
        chars = data.get("chars", 0)
        links = data.get("links_count", 0)
        return f"✅ Fetched: *{title}*\n{chars} chars, {links} links"
