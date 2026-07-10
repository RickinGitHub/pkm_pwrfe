"""Phase 1 tests — M3 message classification (MsgType + ProcessCategory + IncomingMessage)."""

from __future__ import annotations

import pytest

from harness.bot.message_types import (
    IncomingMessage,
    MsgType,
    ProcessCategory,
    classify_message,
)


def _msg(text: str, **kw) -> IncomingMessage:
    return IncomingMessage(
        chat_id=1, user_id=1, msg_type=MsgType.TEXT, text=text, **kw
    )


class TestClassifyCategory:
    def test_file_is_long(self):
        m = IncomingMessage(chat_id=1, user_id=1, msg_type=MsgType.FILE, text="")
        assert m.category == ProcessCategory.LONG
        assert m.is_long_running

    def test_url_is_long(self):
        m = IncomingMessage(chat_id=1, user_id=1, msg_type=MsgType.URL, text="https://x.com")
        assert m.is_long_running

    @pytest.mark.parametrize("cmd", ["/fetch", "/ingest", "/review", "/build", "/crawl"])
    def test_long_commands(self, cmd):
        m = IncomingMessage(chat_id=1, user_id=1, msg_type=MsgType.COMMAND, text=cmd)
        assert m.is_long_running

    def test_interactive_clear(self):
        m = IncomingMessage(chat_id=1, user_id=1, msg_type=MsgType.COMMAND, text="/clear")
        assert m.is_interactive

    def test_instant_command(self):
        m = IncomingMessage(chat_id=1, user_id=1, msg_type=MsgType.COMMAND, text="/calc 2+2")
        assert m.category == ProcessCategory.INSTANT
        assert not m.is_long_running
        assert not m.is_interactive

    def test_plain_text_is_instant(self):
        m = IncomingMessage(chat_id=1, user_id=1, msg_type=MsgType.TEXT, text="hello")
        assert m.category == ProcessCategory.INSTANT


class TestQueryForAgent:
    def test_command_strips_slash(self):
        m = IncomingMessage(chat_id=1, user_id=1, msg_type=MsgType.COMMAND, text="/calc 2+2")
        assert m.query_for_agent == "calc 2+2"

    def test_url_prefixes_fetch(self):
        m = IncomingMessage(chat_id=1, user_id=1, msg_type=MsgType.URL, text="https://x.com/a")
        assert m.query_for_agent == "fetch https://x.com/a"

    def test_text_passthrough(self):
        m = IncomingMessage(chat_id=1, user_id=1, msg_type=MsgType.TEXT, text="hi")
        assert m.query_for_agent == "hi"


class TestClassifyMessage:
    def _update(self, **fields) -> dict:
        base = {"chat": {"id": 42}, "from": {"id": 7}, "date": 1700000000}
        base.update(fields)
        return {"message": base}

    def test_command(self):
        m = classify_message(self._update(text="/start"))
        assert m is not None
        assert m.msg_type == MsgType.COMMAND
        assert m.chat_id == 42
        assert m.user_id == 7

    def test_url(self):
        m = classify_message(self._update(text="https://example.com/x"))
        assert m is not None
        assert m.msg_type == MsgType.URL

    def test_text(self):
        m = classify_message(self._update(text="hello world"))
        assert m is not None
        assert m.msg_type == MsgType.TEXT

    def test_document_file(self):
        m = classify_message(self._update(document={"file_id": "x"}, caption="note"))
        assert m is not None
        assert m.msg_type == MsgType.FILE
        assert m.text == "note"

    def test_callback(self):
        upd = {
            "callback_query": {
                "data": "confirm_ingest:rag/corpus/a.md",
                "message": {"chat": {"id": 9}, "from": {"id": 5}, "date": 1},
            }
        }
        m = classify_message(upd)
        assert m is not None
        assert m.msg_type == MsgType.CALLBACK
        assert m.callback_data == "confirm_ingest:rag/corpus/a.md"

    def test_empty_returns_none(self):
        assert classify_message({}) is None
        assert classify_message({"message": {"chat": {"id": 1}}}) is None
