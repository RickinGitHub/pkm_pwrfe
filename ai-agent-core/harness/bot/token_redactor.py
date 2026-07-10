"""M8 — Token log redactor (logging.Filter, global interception).

Design ref: docs/telegram_bot_design.md §6.2.5
Implementation plan: docs/telegram_bot_implementation_plan.md Phase 1.4
"""

from __future__ import annotations

import logging


class TokenRedactor(logging.Filter):
    """Replace full token occurrences in log records with a short hint."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token or ""
        self._hint = (token[:8] + "...") if token else ""

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._token:
            return True
        msg = record.getMessage()
        if self._token in msg:
            record.msg = msg.replace(self._token, self._hint)
            record.args = None
        return True


def install(token: str) -> TokenRedactor:
    """Attach a TokenRedactor to the root logger and return it."""
    f = TokenRedactor(token)
    logging.getLogger().addFilter(f)
    return f
