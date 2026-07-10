"""Shared worker protocol helpers.

All worker subprocesses emit exactly one JSON line on stdout and exit.
The parent process reads that line to collect the result. Anything
written to stdout outside `emit_result` corrupts the IPC channel.

Usage (inside a worker module)::

    from scripts.bot_workers._worker_base import worker_main, emit_result

    def _run(payload: dict) -> dict:
        ...  # do work
        return {"ok": True, "result": ..., "error": None}

    if __name__ == "__main__":
        worker_main(_run)
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable


def emit_result(result: dict[str, Any]) -> None:
    """Write a single-line JSON result to stdout and flush.

    The parent reads only the LAST non-empty line of stdout, so partial
    writes from libraries that print to stdout are tolerated as long as
    this call is the final stdout write.
    """
    line = json.dumps(result, ensure_ascii=False, default=str)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def worker_main(entry_fn: Callable[[dict], dict], payload: dict | None = None) -> None:
    """Worker entrypoint.

    Reads payload from stdin JSON if not passed directly, calls
    ``entry_fn(payload)``, and emits the result on stdout. Any exception
    is captured and emitted as an error envelope so the parent always
    receives a result.
    """
    try:
        if payload is None:
            raw = sys.stdin.read()
            payload = json.loads(raw) if raw.strip() else {}
        assert payload is not None
        result = entry_fn(payload)
        if not isinstance(result, dict):
            result = {"ok": False, "result": None, "error": f"worker returned non-dict: {type(result).__name__}"}
        emit_result(result)
    except Exception as exc:  # noqa: BLE001 — worker must never crash silently
        emit_result({
            "ok": False,
            "result": None,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
        sys.exit(1)
