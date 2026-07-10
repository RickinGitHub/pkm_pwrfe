"""GenericWorkerChild — run long-running agent commands in a subprocess.

Handles the LONG command set from the design doc:
    /build, /rebuild, /update (similarity edges)
    /ingest, /pipeline, /reindex, /unindex
    /review, /evolve, /reflect

These are agent.handle() calls that take seconds to minutes. They
don't need network-level SSRF checks (unlike /fetch) or file I/O (unlike
file workers) — they're pure agent dispatch. We isolate them in a
subprocess purely for:

1. GIL release — let agent's own threading work without contending with
   the bot's event loop.
2. Crash isolation — a SQLite lock or OOM in pipeline doesn't kill bot.
3. Hard timeout — ``proc.join(timeout=120)`` + SIGKILL beats trying to
   cancel a blocking call inside agent.handle().
"""

from __future__ import annotations

import sys
from typing import Any

from _worker_base import worker_main


def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Payload keys:
    - query: str (required) — full agent query, e.g. "review 历史 中国 朝代"
    - timeout_seconds: int (optional, default 120)
    """
    query = payload.get("query")
    if not query:
        return {"ok": False, "result": None, "error": "missing query"}

    try:
        sys.path.insert(0, ".")
        from harness.factory import build_agent  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "result": None, "error": f"agent import failed: {exc}"}

    try:
        agent = build_agent()
        result = agent.handle(query)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "result": None, "error": f"agent.handle failed: {exc}"}

    return {
        "ok": bool(result.get("ok")),
        "result": result.get("result"),
        "error": result.get("error"),
    }


if __name__ == "__main__":
    worker_main(run)
