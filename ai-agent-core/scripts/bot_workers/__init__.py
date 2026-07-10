"""Telegram bot subprocess workers (renamed from ``scripts/telegram/``).

Modules in this package run inside child processes spawned by the main
Telegram bot (``telegram_bot.py``). They communicate with the parent via
a single-line JSON result on stdout (see ``_worker_base.emit_result``).

Workers must NEVER write to stdout except through ``emit_result``. Use
stderr for logging — it is captured separately by the parent.

Import note: workers import ``_worker_base`` as a flat module because
they are launched with their own directory on ``sys.path``. Do not
switch to package-relative imports without updating the launcher in
``telegram_bot.py::_run_worker_subprocess``.

Naming rationale: the parent-side logic lives in ``harness/bot/`` so
this directory is named ``bot_workers/`` (not ``telegram/``) to avoid
the prior ``harness/telegram/`` vs ``scripts/telegram/`` ambiguity.
"""
