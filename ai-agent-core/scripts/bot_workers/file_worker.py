"""FileWorkerChild — download files sent to the bot by Telegram users.

Triggered when a user uploads a document/photo/voice message. The
parent bot dispatches this worker as a subprocess so that:

1. Large file downloads don't block the asyncio event loop.
2. A crash during download (network, disk full) doesn't kill the bot.
3. Disk I/O happens in an isolated process — easier to clean up on
   timeout (SIGTERM → SIGKILL).

Output lands in ``rag/corpus/telegram/<chat_id>/<safe_name>`` and is
registered in ``memories/telegram_file_registry.json`` so the parent
can later resolve "the file I received in chat X" back to a corpus
path.

Security:
- File names are sanitized via ``Path(name).name`` to drop any path
  components a malicious client might embed.
- Downloads go through the Telegram Bot API HTTPS endpoint only.
- A 50 MB hard cap prevents runaway disk usage.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

from _worker_base import worker_main

TELEGRAM_API_BASE = "https://api.telegram.org"
DEFAULT_CORPUS_DIR = "rag/corpus/telegram"
DEFAULT_REGISTRY = "memories/telegram_file_registry.json"
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB hard cap
DOWNLOAD_TIMEOUT_SECONDS = 60


def _sanitize_filename(name: str) -> str:
    """Strip path components and collapse to a single bare filename."""
    safe = Path(name).name or "file"
    return safe


def _get_download_url(bot_token: str, file_id: str) -> tuple[str, str]:
    """Call getFile API → return (download_url, file_path).

    Raises RuntimeError on any API error.
    """
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/getFile"
    payload = json.dumps({"file_id": file_id}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
        body = json.loads(resp.read().decode())
    if not body.get("ok"):
        raise RuntimeError(f"getFile failed: {body.get('description', 'unknown')}")
    file_path = body["result"]["file_path"]
    download_url = f"{TELEGRAM_API_BASE}/file/bot{bot_token}/{file_path}"
    return download_url, file_path


def _download(url: str, dest: Path) -> int:
    """Stream download to ``dest``. Returns bytes written."""
    bytes_written = 0
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
        with dest.open("wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > MAX_FILE_SIZE_BYTES:
                    raise RuntimeError(f"file exceeds {MAX_FILE_SIZE_BYTES} bytes")
                f.write(chunk)
    return bytes_written


def _register(registry_path: Path, entry: dict[str, Any]) -> None:
    """Append-only registry update (atomic-ish: read-modify-write)."""
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    data: list[dict[str, Any]] = []
    if registry_path.exists():
        try:
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                data = []
        except json.JSONDecodeError:
            data = []
    data.append(entry)
    tmp = registry_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(registry_path)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Entry point. Payload keys:
    - bot_token: str (required)
    - file_id: str (required)
    - original_name: str (required, from message.document.file_name or synthesized)
    - chat_id: int (required)
    - user_id: int (required)
    - corpus_dir: str (optional, defaults to rag/corpus/telegram)
    - registry_path: str (optional, defaults to memories/telegram_file_registry.json)
    """
    bot_token = payload.get("bot_token")
    file_id = payload.get("file_id")
    original_name = payload.get("original_name") or "file"
    chat_id = payload.get("chat_id")
    user_id = payload.get("user_id")
    if not (bot_token and file_id and chat_id and user_id):
        return {"ok": False, "result": None, "error": "missing required payload keys"}

    corpus_dir = Path(payload.get("corpus_dir", DEFAULT_CORPUS_DIR)) / str(chat_id)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    registry_path = Path(payload.get("registry_path", DEFAULT_REGISTRY))

    safe_name = _sanitize_filename(original_name)
    dest = corpus_dir / safe_name
    # If collision, append timestamp suffix to avoid overwrite.
    if dest.exists():
        stem, ext = os.path.splitext(safe_name)
        dest = corpus_dir / f"{stem}.{int(time.time())}{ext}"

    try:
        download_url, remote_path = _get_download_url(bot_token, file_id)
        size = _download(download_url, dest)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "result": None, "error": f"download failed: {exc}"}

    entry = {
        "chat_id": chat_id,
        "user_id": user_id,
        "file_id": file_id,
        "original_name": original_name,
        "safe_name": dest.name,
        "local_path": str(dest),
        "remote_path": remote_path,
        "size": size,
        "received_at": time.time(),
    }
    try:
        _register(registry_path, entry)
    except Exception as exc:  # noqa: BLE001
        # File landed; registry is best-effort.
        return {
            "ok": True,
            "result": {"path": str(dest), "size": size, "name": dest.name, "registry_warning": str(exc)},
            "error": None,
        }

    return {"ok": True, "result": {"path": str(dest), "size": size, "name": dest.name}, "error": None}


if __name__ == "__main__":
    worker_main(run)
