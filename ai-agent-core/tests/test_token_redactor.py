"""Phase 1 tests — M8 token redactor."""

from __future__ import annotations

import logging

from harness.bot.token_redactor import TokenRedactor


def _make_record(msg: str, token: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg=msg, args=None, exc_info=None,
    )


class TestTokenRedactor:
    def test_replaces_token_with_hint(self):
        r = TokenRedactor("1234567890ABCDEF")
        rec = _make_record("error: token=1234567890ABCDEF failed", "1234567890ABCDEF")
        assert r.filter(rec) is True
        assert "1234567890ABCDEF" not in rec.getMessage()
        assert "12345678..." in rec.getMessage()

    def test_no_token_passthrough(self):
        r = TokenRedactor("")
        rec = _make_record("plain log message", "")
        assert r.filter(rec) is True
        assert rec.getMessage() == "plain log message"

    def test_token_not_present_unchanged(self):
        r = TokenRedactor("SECRET123")
        rec = _make_record("unrelated message", "SECRET123")
        assert r.filter(rec) is True
        assert rec.getMessage() == "unrelated message"

    def test_partial_token_not_replaced(self):
        r = TokenRedactor("ABCDEFGH")
        rec = _make_record("got ABCDEF from server", "ABCDEFGH")
        assert r.filter(rec) is True
        # Only the full token is replaced; partial substring stays
        assert "ABCDEF" in rec.getMessage()

    def test_hint_format(self):
        r = TokenRedactor("1234567890")
        assert r._hint == "12345678..."
