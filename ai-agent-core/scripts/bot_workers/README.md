# Telegram Bot Subprocess Workers

Workers run in child processes spawned by the main Telegram bot
([`telegram_bot.py`](../../telegram_bot.py)). Each worker emits
exactly **one JSON line on stdout** and exits. The parent reads that
line as the result.

> **Naming note**: this directory was renamed from `scripts/telegram/`
> to `scripts/bot_workers/` to disambiguate from the parent-side
> `harness/bot/` (which holds the main-process logic). The
> `rag/corpus/telegram/` corpus dir and `memories/telegram_sessions/`
> runtime data dir are unrelated to this package name.

## Why subprocess, not thread pool

| Concern | Thread pool | Subprocess |
|---------|-------------|------------|
| GIL contention with bot event loop | yes | no |
| Crash isolation | process crash kills bot | isolated |
| Hard timeout | urllib socket timeout unreliable | `proc.join(timeout)` + `SIGKILL` reliable |
| Resource cleanup (open FDs, sqlite handles) | leaks back to bot | OS reaps everything on exit |

## Modules

| File | Role | Triggered by |
|------|------|--------------|
| [`_worker_base.py`](_worker_base.py) | `emit_result` + `worker_main` IPC protocol | (shared) |
| [`message_types.py`](message_types.py) | `IpcMessage` read-only view, `from_ipc_dict` | (shared) |
| [`chat_cache.py`](chat_cache.py) | read recent JSONL history (no writes) | any worker needing context |
| [`session_manager.py`](session_manager.py) | read `session.json` (no writes) | any worker needing pending_action |
| [`file_worker.py`](file_worker.py) | download user-uploaded file → `rag/corpus/telegram/<chat>/` | FILE message |
| [`send_file_worker.py`](send_file_worker.py) | send corpus file back to user via `sendDocument` | `/getfile <path>` |
| [`url_worker.py`](url_worker.py) | SSRF-check → `agent.handle("fetch <url>")` | URL in message, `/fetch` |
| [`generic_worker.py`](generic_worker.py) | `agent.handle(query)` for LONG commands | `/build`, `/ingest`, `/review`, `/reflect`, ... |

## IPC protocol

Parent → child: JSON on stdin (one object).

Child → parent: exactly one JSON line on stdout (last non-empty line
wins). Everything else must go to stderr.

```
{"ok": true, "result": <any>, "error": null}
```

On any exception, the worker emits an error envelope with a `traceback`
field and exits with code 1. The parent treats non-zero exit codes as
failure but still parses stdout for a result if present.

## Import convention

Workers import `_worker_base` as a flat module. The parent launches them
with `cwd=ai-agent-core/` and the `scripts/bot_workers/` directory
prepended to `sys.path` (via `PYTHONPATH` or explicit insert). Do **not**
switch to package-relative imports — it breaks the flat-import style.

## Running a worker standalone (debugging)

```bash
cd ai-agent-core
echo '{"url":"https://example.com"}' | PYTHONPATH=scripts/bot_workers python3 scripts/bot_workers/url_worker.py
# → one JSON line on stdout
```

All workers accept a JSON payload on stdin when launched with no argv,
or you can pass the payload programmatically by importing the module
and calling `run(payload_dict)` directly.

## Concurrency

- Global cap: `asyncio.Semaphore(4)` across all LONG workers.
- Per-chat cap: at most 2 concurrent LONG workers per chat.
- Timeout: `proc.join(timeout=120)` → `SIGTERM` → 5s → `SIGKILL`.

## Security guarantees per worker

| Worker | Path safety | Network safety | Size cap |
|--------|-------------|----------------|----------|
| file_worker | `Path(name).name` sanitize | Telegram API HTTPS only | 50 MB |
| send_file_worker | 3-tier (resolve + `relative_to` + `is_symlink`) | Telegram API HTTPS only | 50 MB |
| url_worker | n/a | SSRF (`_BLOCKED_NETS`, all `getaddrinfo` results checked) | n/a |
| generic_worker | n/a | n/a (only calls `agent.handle`) | n/a |
