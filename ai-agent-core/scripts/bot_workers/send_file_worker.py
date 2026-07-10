"""SendFileChild — send a corpus file back to the user via sendDocument.

Triggered when a user requests a file by name or path. Three-tier path
safety ensures only corpus files leave the bot:

1. Path canonicalization: ``Path(req).resolve()`` collapses ``..`` and
   symlinks.
2. Corpus prefix check: resolved path must be inside
   ``rag/corpus/`` (``relative_to`` raises if not a subpath).
3. Symlink guard: ``is_symlink()`` rejects any symlink even if it
   resolves into the corpus (TOCCTOU defense).

A 50 MB cap mirrors the upload side — Telegram's bot API limit is 50 MB
for sendDocument.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

from _worker_base import worker_main

TELEGRAM_API_BASE = "https://api.telegram.org"
CORPUS_ROOT = Path("rag/corpus").resolve()
MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB Telegram cap
UPLOAD_TIMEOUT_SECONDS = 120


def _validate_path(requested: str) -> Path:
    """Three-tier path safety. Raises ValueError on any violation."""
    candidate = Path(requested).expanduser()
    if candidate.is_symlink():
        raise ValueError("symlinks not allowed")
    resolved = candidate.resolve()
    if not resolved.exists():
        raise ValueError(f"no such file: {requested}")
    if not resolved.is_file():
        raise ValueError(f"not a file: {requested}")
    resolved.relative_to(CORPUS_ROOT)  # raises ValueError if outside
    if resolved.stat().st_size > MAX_UPLOAD_SIZE_BYTES:
        raise ValueError(f"file exceeds {MAX_UPLOAD_SIZE_BYTES} bytes")
    return resolved


def _send_document(bot_token: str, chat_id: int, file_path: Path, caption: str | None) -> dict[str, Any]:
    """POST sendDocument with multipart form. Returns parsed API response."""
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendDocument"
    boundary = "----telegramboundary" + os.urandom(8).hex()
    filename = file_path.name

    with file_path.open("rb") as f:
        file_bytes = f.read()

    body_parts: list[bytes] = []
    # chat_id field
    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
    body_parts.append(f"{chat_id}\r\n".encode())
    # caption (optional)
    if caption:
        body_parts.append(f"--{boundary}\r\n".encode())
        body_parts.append(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
        body_parts.append(f"{caption}\r\n".encode())
    # document field
    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode()
    )
    body_parts.append(b"Content-Type: application/octet-stream\r\n\r\n")
    body_parts.append(file_bytes)
    body_parts.append(b"\r\n")
    body_parts.append(f"--{boundary}--\r\n".encode())

    body = b"".join(body_parts)
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=UPLOAD_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode())


def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Payload keys:
    - bot_token: str (required)
    - chat_id: int (required)
    - path: str (required) — absolute, relative, or bare filename; resolved under rag/corpus
    - caption: str (optional)
    """
    bot_token = payload.get("bot_token")
    chat_id = payload.get("chat_id")
    requested_path = payload.get("path")
    caption = payload.get("caption")
    if not (bot_token and chat_id and requested_path):
        return {"ok": False, "result": None, "error": "missing required payload keys"}

    # Bare-name convenience: resolve under CORPUS_ROOT.
    if os.path.sep not in requested_path and "/" not in requested_path:
        requested_path = str(CORPUS_ROOT / requested_path)

    try:
        resolved = _validate_path(requested_path)
    except ValueError as exc:
        return {"ok": False, "result": None, "error": str(exc)}

    try:
        api_resp = _send_document(bot_token, int(chat_id), resolved, caption)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "result": None, "error": f"sendDocument failed: {exc}"}

    if not api_resp.get("ok"):
        return {"ok": False, "result": None, "error": f"telegram API: {api_resp.get('description')}"}

    return {
        "ok": True,
        "result": {
            "message_id": api_resp.get("result", {}).get("message_id"),
            "path": str(resolved),
            "size": resolved.stat().st_size,
        },
        "error": None,
    }


if __name__ == "__main__":
    worker_main(run)
