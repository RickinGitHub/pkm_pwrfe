"""Telegram bot main-process modules (M3/M5/M6/M7/M8/M10).

Renamed from the prior ``harness/telegram/`` plan to avoid the ambiguity
with ``scripts/telegram/`` (now ``scripts/bot_workers/``). This package
holds the main-process side: message classification, response formatting,
per-chat session state, chat cache, and security controls.

Subprocess workers live in ``scripts/bot_workers/`` and use flat imports
(``_worker_base``), not package-relative imports.
"""
