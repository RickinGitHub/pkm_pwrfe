# -*- coding: utf-8 -*-
"""Telegram bot daemon — long-polling entry point for ai-agent-core.

Process management (mirrors server.py / review_cron.py / background_worker.py):
    python3 telegram_bot.py run [--token xxx]      # 前台运行（调试用）
    python3 telegram_bot.py start [--token xxx]    # 后台启动
    python3 telegram_bot.py stop                   # 停止后台进程
    python3 telegram_bot.py restart [--token xxx]  # 重启后台进程
    python3 telegram_bot.py status                 # 查看后台状态

环境变量：
    TELEGRAM_BOT_TOKEN             Bot token from @BotFather（必填）
    TELEGRAM_ALLOWED_USER_IDS      逗号分隔白名单（空=拒绝所有人，"*"=公开）
    TELEGRAM_PID_FILE              PID 文件路径（默认 memories/telegram_bot.pid）
    TELEGRAM_LOG_FILE              后台日志文件（默认 memories/telegram_bot.log）
    TELEGRAM_POLL_TIMEOUT_SECONDS  长轮询超时（默认 30）
    TELEGRAM_QUEUE_MAXSIZE         消息队列上限（默认 100）
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

_HERE = Path(__file__).resolve().parent
load_dotenv(_HERE / ".env")

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

_DEFAULT_PID_FILE = _HERE / "memories" / "telegram_bot.pid"
_DEFAULT_LOG_FILE = _HERE / "memories" / "telegram_bot.log"
_SCRIPT_NAME = "telegram_bot.py"

# Logging: always write to file; also output to terminal (basicConfig handles stderr)
_LOG_FILE = Path(os.environ.get("TELEGRAM_LOG_FILE", _DEFAULT_LOG_FILE))
_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=os.environ.get("TELEGRAM_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(_LOG_FILE), encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
    force=True,
)
log = logging.getLogger("telegram_bot")

from harness.daemon import (  # noqa: E402
    pid_file_path as _daemon_pid_file_path,
    read_pid as _daemon_read_pid,
    write_pid as _daemon_write_pid,
    remove_pid as _daemon_remove_pid,
    is_running as _daemon_is_running,
    read_pid_cmdline as _daemon_read_pid_cmdline,
    find_orphan_pids as _daemon_find_orphan_pids,
    terminate_pid as _daemon_terminate_pid,
)


# ---------------------------------------------------------------------------
# PID / log 辅助
# ---------------------------------------------------------------------------

def _pid_file() -> Path:
    return _daemon_pid_file_path("TELEGRAM_PID_FILE", _DEFAULT_PID_FILE)


def _log_file() -> Path:
    return Path(os.environ.get("TELEGRAM_LOG_FILE", _DEFAULT_LOG_FILE))


def _read_pid() -> int | None:
    return _daemon_read_pid("TELEGRAM_PID_FILE", _DEFAULT_PID_FILE)


def _write_pid(pid: int) -> None:
    _daemon_write_pid("TELEGRAM_PID_FILE", _DEFAULT_PID_FILE, pid)


def _remove_pid() -> None:
    _daemon_remove_pid("TELEGRAM_PID_FILE", _DEFAULT_PID_FILE)


def _is_running(pid: int) -> bool:
    return _daemon_is_running(pid)


def _find_orphans(exclude: int | None = None) -> list[int]:
    return _daemon_find_orphan_pids(_SCRIPT_NAME, exclude=exclude)


# ---------------------------------------------------------------------------
# 公共参数
# ---------------------------------------------------------------------------

def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--token",
        default=None,
        help="Bot token（默认从 TELEGRAM_BOT_TOKEN 环境变量读取）",
    )


def _resolve_token(args_token: str | None) -> str:
    token = args_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        log.error(
            "Telegram bot token is required. "
            "Set TELEGRAM_BOT_TOKEN in .env or pass --token."
        )
        sys.exit(1)
    return token


# ---------------------------------------------------------------------------
# run — 前台运行
# ---------------------------------------------------------------------------

def cmd_run(token: str) -> int:
    """Foreground long-polling loop (for debugging)."""
    log.info("starting telegram bot in foreground...")
    _run_polling_loop(token)
    return 0


def _build_telegram_api_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _detect_proxy() -> str | None:
    """Detect proxy for Telegram API from multiple sources.

    Priority:
    1. TELEGRAM_PROXY env var (explicit config in .env)
    2. https_proxy / HTTP_PROXY env vars (set by proxy tools automatically)
    3. Windows system proxy settings (registry)
    4. Common local proxy ports (auto-detect)
    """
    # 1. Explicit config
    proxy = os.environ.get("TELEGRAM_PROXY")
    if proxy:
        log.info("proxy: from TELEGRAM_PROXY=%s", proxy)
        return proxy

    # 2. System env vars (set by Clash/V2Ray/SSR etc.)
    for var in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
        val = os.environ.get(var)
        if val:
            log.info("proxy: from %s=%s", var, val)
            return val

    # 3. Windows system proxy (registry)
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enable = winreg.QueryValueEx(key, "ProxyEnable")[0]
            server = winreg.QueryValueEx(key, "ProxyServer")[0]
            if enable and server:
                if not server.startswith("http://") and not server.startswith("socks"):
                    server = f"http://{server}"
                log.info("proxy: from Windows system settings = %s", server)
                return server
    except Exception:
        pass

    # 4. Auto-detect common proxy ports
    import socket
    common_ports = [7890, 10809, 10808, 1080, 8080, 3128]
    for port in common_ports:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=0.5)
            s.close()
            proxy = f"http://127.0.0.1:{port}"
            log.info("proxy: auto-detected http://127.0.0.1:%s", port)
            return proxy
        except (OSError, socket.timeout):
            continue

    log.info("proxy: none detected, connecting directly")
    return None


def _telegram_session() -> requests.Session:
    """Create a requests.Session for Telegram API calls.

    Auto-detects proxy from multiple sources (TELEGRAM_PROXY → env vars → common ports).
    """
    session = requests.Session()
    proxy = _detect_proxy()
    if proxy:
        session.proxies.update({"https": proxy, "http": proxy})
    return session


def _renew_session(
    old_session: requests.Session | None,
    token: str,
) -> requests.Session:
    """Create a fresh session with re-detected proxy.

    Closes old session if provided. Used to recover from proxy changes.
    """
    if old_session is not None:
        try:
            old_session.close()
        except Exception:
            pass
    new_session = _telegram_session()
    # Quick connectivity check (non-blocking, 3s timeout)
    try:
        resp = new_session.get(
            _build_telegram_api_url(token, "getMe"),
            timeout=3,
        )
        if resp.ok:
            bot_info = resp.json().get("result", {})
            log.info(
                "session renewed ✅ connected as @%s",
                bot_info.get("username", "?"),
            )
        else:
            log.warning("session renewed but getMe returned HTTP %s", resp.status_code)
    except requests.RequestException as e:
        log.warning("session renewed but API unreachable: %s", e)
    return new_session


def _sanitize_markdown(text: str) -> str:
    """Remove unclosed Markdown formatting entities that cause Telegram parse errors."""
    import re
    # Close all unpaired **, __, ~~ by removing the last orphan
    for marker in ['**', '__', '~~']:
        count = text.count(marker)
        if count % 2 != 0:
            idx = text.rfind(marker)
            if idx != -1:
                text = text[:idx] + text[idx + len(marker):]
    # Handle ``` code blocks (must have 0, 2, 4... occurrences)
    count = text.count('```')
    if count % 2 != 0:
        idx = text.rfind('```')
        if idx != -1:
            text = text[:idx] + text[idx + 3:]
    # Escape bare * and _ that could be interpreted as formatting
    # Surround bare * / _ with spaces if they're alone on a line
    return text


def _send_message(token: str, chat_id: int, text: str, reply_to: int | None = None, session: requests.Session | None = None) -> bool:
    """Send a text message to a Telegram chat. Retries once on timeout.
    Falls back to plain text if Markdown parsing fails."""
    close_session = False
    if session is None:
        session = _telegram_session()
        close_session = True

    text = _sanitize_markdown(text)
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if reply_to is not None:
        payload["reply_to_message_id"] = reply_to
    for attempt in range(2):
        try:
            resp = session.post(
                _build_telegram_api_url(token, "sendMessage"),
                json=payload,
                timeout=15,
            )
            if resp.ok:
                if close_session:
                    session.close()
                return True
            # If Markdown parsing failed, retry without parse_mode
            if resp.status_code == 400 and "parse entities" in resp.text.lower():
                log.warning("Markdown parse error, retrying as plain text")
                payload.pop("parse_mode", None)
                resp = session.post(
                    _build_telegram_api_url(token, "sendMessage"),
                    json=payload,
                    timeout=15,
                )
                if resp.ok:
                    if close_session:
                        session.close()
                    return True
            log.warning("sendMessage failed: HTTP %s %s", resp.status_code, resp.text[:200])
            if close_session:
                session.close()
            return False
        except requests.RequestException as e:
            log.warning("sendMessage attempt %d/2 error: %s", attempt + 1, e)
            if attempt == 0:
                time.sleep(1.0)
    if close_session:
        session.close()
    return False


def _worker_entry_point(worker_path: str, payload: dict) -> None:
    """Subprocess entry: import worker module, call run(payload), emit result via stdout.

    This is the ``target`` for ``multiprocessing.Process``.
    The actual worker module is loaded dynamically to avoid importing
    all workers into the parent process.
    """
    import importlib.util
    import sys as _sys

    try:
        # Add project root to path so relative imports work
        project_root = str(_HERE)
        if project_root not in _sys.path:
            _sys.path.insert(0, project_root)

        # Load worker module from its file path
        module_name = Path(worker_path).stem
        spec = importlib.util.spec_from_file_location(module_name, worker_path)
        if spec is None or spec.loader is None:
            _sys.stdout.write('{"ok":false,"result":null,"error":"failed to load worker module"}\n')
            _sys.stdout.flush()
            _sys.exit(1)

        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Call run(payload) — all workers export this
        if not hasattr(mod, "run"):
            _sys.stdout.write('{"ok":false,"result":null,"error":"worker module has no run()"}\n')
            _sys.stdout.flush()
            _sys.exit(1)

        result = mod.run(payload)
        line = json.dumps(result, ensure_ascii=False, default=str)
        _sys.stdout.write(line + "\n")
        _sys.stdout.flush()
        _sys.exit(0)
    except Exception as exc:
        _sys.stdout.write(
            json.dumps({"ok": False, "result": None, "error": f"{type(exc).__name__}: {exc}"},
                       ensure_ascii=False)
            + "\n"
        )
        _sys.stdout.flush()
        _sys.exit(1)


def _handle_interactive(
    msg: Any,
    state: Any,
    sessions: Any,
) -> str:
    """INTERACTIVE: set pending_action, return a confirmation prompt text.

    Design ref: docs/telegram_bot_design.md §4.6.4
    """
    text = msg.text.strip().lower()

    if text.startswith("/clear"):
        state.set_pending("await_clear_confirm", {})
        sessions.save(msg.chat_id)
        return "确认清空会话历史？\n\n发送 ✅ 确认 或 ❌ 取消"

    # Future INTERACTIVE commands can be added here
    return f"⚠️ 未知的交互命令: {text}"


def _run_polling_loop(token: str) -> None:
    """Entry point: asyncio.Queue + single worker + subprocess dispatch (§5.3).

    1. Poller thread pushes IncomingMessage to asyncio.Queue (non-blocking).
    2. Single Worker (asyncio.Task) consumes from the queue.
    3. Dispatch by ProcessCategory: INSTANT / LONG / INTERACTIVE.
    """
    import asyncio

    # ── Sync setup (agent, whitelist, state) ──
    try:
        old_cwd = Path.cwd()
        os.chdir(str(_HERE))
        from harness.factory import build_agent
        agent = build_agent()
        os.chdir(str(old_cwd))
        log.info("agent built successfully")
    except Exception as e:
        log.error("failed to build agent: %s", e)
        log.info("running in relay-only mode (no agent dispatch)")
        agent = None

    allowed_raw = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").strip()
    if allowed_raw == "*":
        allowed_users: set[int] | None = None
        log.info("user whitelist: public mode (*)")
    elif allowed_raw:
        allowed_users = {int(x.strip()) for x in allowed_raw.split(",") if x.strip()}
        log.info("user whitelist: %s", allowed_users)
    else:
        allowed_users = set()
        log.warning("user whitelist: empty — all users will be rejected")

    from harness.bot.message_types import classify_message
    from harness.bot.token_redactor import install as install_token_redactor
    from harness.bot.session_manager import SessionManager
    from harness.bot.chat_cache import ChatCache
    from harness.bot.response_formatter import ResponseFormatter
    install_token_redactor(token)

    sessions = SessionManager()
    chat_cache = ChatCache()

    # ── Session / proxy lifecycle (shared across threads) ──
    _session_lock = threading.Lock()
    tg_session = _telegram_session()

    def _get_session() -> requests.Session:
        with _session_lock:
            return tg_session

    def _hot_reload_session() -> requests.Session:
        nonlocal tg_session
        with _session_lock:
            tg_session = _renew_session(tg_session, token)
            return tg_session

    # Proxy connectivity test
    try:
        test_resp = _get_session().get(_build_telegram_api_url(token, "getMe"), timeout=5)
        if test_resp.ok:
            bot_info = test_resp.json().get("result", {})
            log.info("Telegram API connected ✅ as @%s", bot_info.get("username", "?"))
        else:
            log.warning("Telegram API test failed: HTTP %s", test_resp.status_code)
    except requests.RequestException as e:
        log.warning("Telegram API unreachable: %s", e)
        log.info("💡 Set TELEGRAM_PROXY=http://127.0.0.1:7890 in .env if Telegram is blocked")

    # ── Shared state ──
    stop_event = threading.Event()
    offset_lock = threading.Lock()
    offset = 0
    agent_lock = threading.Lock()  # §5.3: agent.handle() is not thread-safe
    msg_queue: asyncio.Queue = asyncio.Queue(
        maxsize=int(os.environ.get("TELEGRAM_QUEUE_MAXSIZE", "100")),
    )

    def _stop(*_: Any) -> None:
        log.info("stop signal received")
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    poll_timeout = int(os.environ.get("TELEGRAM_POLL_TIMEOUT_SECONDS", "10"))

    # ── Helper: build preamble from chat history (§4.3) ──
    def _build_enhanced_query(msg: Any) -> str:
        query = msg.query_for_agent
        history = chat_cache.get_context(msg.chat_id, limit=10)
        if not history:
            return query
        preamble_lines = []
        for h in history:
            role = h.get("role", "")
            content = str(h.get("content", ""))[:200]
            if role in ("user", "assistant") and content:
                preamble_lines.append(f"[{role}] {content}")
        return "\n".join(preamble_lines) + f"\n\n[current question] {query}"

    # ── Worker dispatch helpers (§5.3) ──

    def _pick_worker_module(msg: Any) -> str:
        """Return the worker module name for a LONG message."""
        if msg.msg_type.name == "FILE":
            return "file_worker"
        text_lower = msg.text.strip().lower()
        if text_lower.startswith("/getfile"):
            return "send_file_worker"
        if text_lower.startswith(("/fetch", "/crawl", "/抓取", "/下载")):
            return "url_worker"
        if msg.msg_type.name == "URL":
            return "url_worker"
        return "generic_worker"

    def _build_worker_payload(msg: Any, token: str) -> dict[str, Any]:
        """Build the correct payload dict for the worker matched to *msg*.

        Each worker module expects a specific set of keys — see the
        individual ``run(payload)`` docstrings.
        """
        worker_module = _pick_worker_module(msg)
        base = msg.to_ipc_dict()

        if worker_module == "file_worker":
            # Extract file_id / original_name from the raw Telegram update
            raw = msg.raw if isinstance(msg.raw, dict) else {}
            inner = raw.get("message") or raw.get("callback_query", {}).get("message") or {}
            file_id: str | None = None
            file_name: str = "file"
            for file_key in ("document", "audio", "video", "voice"):
                fobj = inner.get(file_key)
                if isinstance(fobj, dict):
                    file_id = fobj.get("file_id") or file_id
                    file_name = fobj.get("file_name") or file_name
            # photo is a list of PhotoSize objects; use the largest
            photo_list = inner.get("photo")
            if photo_list and isinstance(photo_list, list) and len(photo_list) > 0:
                largest = photo_list[-1]
                if isinstance(largest, dict):
                    file_id = largest.get("file_id") or file_id
                    file_name = f"{file_id}.jpg" if file_id else "photo.jpg"
            return {
                "bot_token": token,
                "file_id": file_id or "",
                "original_name": file_name,
                "chat_id": msg.chat_id,
                "user_id": msg.user_id,
                "corpus_dir": os.environ.get("TELEGRAM_DOWNLOAD_DIR", "rag/corpus/telegram"),
                "registry_path": "memories/telegram_file_registry.json",
            }

        if worker_module == "send_file_worker":
            # /getfile <path> — extract path from text
            parts = msg.text.split(maxsplit=1)
            file_path = parts[1].strip() if len(parts) > 1 else ""
            return {
                "bot_token": token,
                "chat_id": msg.chat_id,
                "path": file_path,
                "caption": None,
            }

        if worker_module == "url_worker":
            # URL message or /fetch <url> — extract the raw URL
            url = msg.text.strip()
            if msg.msg_type.name == "COMMAND":
                # /fetch https://example.com → strip command prefix
                parts = url.split(maxsplit=1)
                url = parts[1].strip() if len(parts) > 1 else url
            return {
                "url": url,
                "extra_args": [],
                "agent_available": True,
            }

        # generic_worker — all other LONG commands
        return {
            "query": _build_enhanced_query(msg),
            "timeout_seconds": int(os.environ.get("TELEGRAM_WORKER_TIMEOUT_SECONDS", "120")),
        }

    def _run_worker_subprocess(msg: Any, token: str) -> dict[str, Any]:
        """Spawn a subprocess worker via subprocess.Popen (§5.6.3).

        IPC protocol: worker reads payload JSON from stdin, writes result
        JSON as LAST line on stdout.
        """
        worker_module = _pick_worker_module(msg)
        payload = _build_worker_payload(msg, token)

        import subprocess as _subprocess

        worker_path = _HERE / "scripts" / "bot_workers" / f"{worker_module}.py"
        payload_json = json.dumps(payload, ensure_ascii=False, default=str)

        proc = _subprocess.Popen(
            [sys.executable, str(worker_path)],
            stdin=_subprocess.PIPE,
            stdout=_subprocess.PIPE,
            stderr=_subprocess.PIPE,
            text=False,
            cwd=str(_HERE),
        )
        stdout_data, stderr_data = proc.communicate(
            input=payload_json.encode("utf-8"),
            timeout=int(os.environ.get("TELEGRAM_WORKER_TIMEOUT_SECONDS", "120")),
        )

        stdout_str = stdout_data.decode("utf-8", errors="replace") if stdout_data else ""
        stderr_str = stderr_data.decode("utf-8", errors="replace") if stderr_data else ""

        if stderr_str.strip():
            for line in stderr_str.strip().splitlines():
                log.warning("worker stderr: %s", line)

        if proc.returncode != 0:
            return {"ok": False, "result": None, "error": f"worker exit code {proc.returncode}"}

        # Read last non-empty line from stdout (IPC protocol)
        lines = [l for l in stdout_str.splitlines() if l.strip()]
        if not lines:
            return {"ok": False, "result": None, "error": "worker produced no output"}
        try:
            return json.loads(lines[-1])
        except (json.JSONDecodeError, IndexError) as e:
            return {"ok": False, "result": None, "error": f"worker stdout parse error: {e}"}

    def _handle_instant(msg: Any, enhanced_query: str) -> str:
        """INSTANT: agent.handle() with lock, then ResponseFormatter."""
        nonlocal agent
        if agent is None:
            return "🤖 Agent not available."

        try:
            with agent_lock:
                result = agent.handle(enhanced_query)
            bot_resp = ResponseFormatter.format(result, msg)
            reply = bot_resp.text
            if not result.get("ok"):
                error_msg = result.get("error", "unknown error")
                if "401" in str(error_msg) or "Authorization" in str(error_msg) or "API_KEY" in str(error_msg):
                    reply = "⚠️ LLM API key 无效或未配置，请检查 `.env` 中的 `OPENAI_API_KEY` 或 `ANTHROPIC_API_KEY`。"
            return reply
        except Exception as e:
            log.exception("agent.handle() failed")
            return f"❌ Internal error: {e}"

    def _handle_long(msg: Any) -> str:
        """LONG: spawn subprocess worker, await result, format response."""
        result = _run_worker_subprocess(msg, token)
        msg.worker_result = result
        bot_resp = ResponseFormatter.format(result, msg)
        reply = bot_resp.text
        if not result.get("ok"):
            error_msg = result.get("error", "unknown error")
            reply = f"❌ {error_msg}"
        return reply

    # ── Asyncio worker loop (Single Worker, §5.3) ──
    async def _worker_loop() -> None:
        """Single async worker: consumes from msg_queue, dispatches by category."""
        while not stop_event.is_set():
            try:
                msg = await asyncio.wait_for(msg_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                chat_id = msg.chat_id
                state = sessions.get_or_create(chat_id)
                state.touch()

                query = msg.query_for_agent
                chat_cache.append(chat_id, "user", query, msg.msg_type.name)

                if msg.is_interactive:
                    reply = _handle_interactive(msg, state, sessions)
                    chat_cache.append(chat_id, "assistant", reply, "BOT", True)
                    sessions.save(chat_id)
                elif msg.is_long_running:
                    reply = _handle_long(msg)
                    chat_cache.append(chat_id, "assistant", reply, "BOT", True)
                    sessions.save(chat_id)
                else:
                    enhanced_query = _build_enhanced_query(msg)
                    reply = _handle_instant(msg, enhanced_query)
                    chat_cache.append(chat_id, "assistant", reply, "BOT", True)
                    sessions.save(chat_id)

                # Truncate & send
                if len(reply) > 4000:
                    reply = reply[:4000] + "\n\n…(truncated)"
                _send_message(
                    token, chat_id, reply,
                    reply_to=msg.raw.get("message_id") if isinstance(msg.raw, dict) else None,
                    session=_get_session(),
                )
            except Exception as e:
                log.exception("worker_loop: unhandled error processing message")
                try:
                    _send_message(token, msg.chat_id, f"❌ Internal error: {e}", session=_get_session())
                except Exception:
                    pass
            finally:
                msg_queue.task_done()

    # ── Sync poller thread ──
    def _poller_thread() -> None:
        """Sync HTTP long-poll in a daemon thread; pushes to asyncio.Queue."""
        nonlocal offset
        consecutive_errors = 0
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Reset stale polling session
        try:
            _get_session().post(
                _build_telegram_api_url(token, "getUpdates"),
                json={"offset": -1, "timeout": 1},
                timeout=5,
            )
        except requests.RequestException:
            pass

        log.info("poller thread started (token=%s...)", token[:8] if len(token) > 8 else "?")

        while not stop_event.is_set():
            # Hot-reload after 3 consecutive errors
            if consecutive_errors >= 3:
                log.info("too many consecutive errors — re-detecting proxy")
                _hot_reload_session()
                consecutive_errors = 0
                stop_event.wait(2.0)
                continue

            try:
                resp = _get_session().post(
                    _build_telegram_api_url(token, "getUpdates"),
                    json={
                        "offset": offset,
                        "timeout": poll_timeout,
                        "allowed_updates": ["message", "callback_query"],
                    },
                    timeout=poll_timeout + 10,
                )
            except requests.RequestException as e:
                consecutive_errors += 1
                delay = min(2 ** (consecutive_errors - 1), 15)
                log.warning("getUpdates error (attempt %d): %s — retry in %ds", consecutive_errors, e, delay)
                if not stop_event.is_set():
                    stop_event.wait(delay)
                continue

            consecutive_errors = 0

            if not resp.ok:
                if resp.status_code == 409:
                    log.warning("getUpdates 409 conflict — resetting...")
                    try:
                        _get_session().post(
                            _build_telegram_api_url(token, "getUpdates"),
                            json={"offset": -1, "timeout": 1},
                            timeout=5,
                        )
                    except requests.RequestException:
                        pass
                    stop_event.wait(3.0)
                    continue
                log.warning("getUpdates HTTP %s: %s", resp.status_code, resp.text[:200])
                stop_event.wait(2.0)
                continue

            for update in resp.json().get("result", []):
                update_id = update.get("update_id", 0)
                if update_id >= offset:
                    offset = update_id + 1

                msg = classify_message(update)
                if msg is None:
                    continue

                # Authorization check
                if allowed_users is not None and msg.user_id not in allowed_users:
                    log.info("blocked message from unauthorized user %d", msg.user_id)
                    _send_message(token, msg.chat_id, "⛔ You are not authorized.", session=_get_session())
                    continue

                if agent is None:
                    _send_message(
                        token, msg.chat_id,
                        "🤖 Relay-only mode (agent not available).",
                        session=_get_session(),
                    )
                    continue

                log.info("enqueue: chat=%d type=%s cat=%s text=%s",
                         msg.chat_id, msg.msg_type.name, msg.category.name, msg.text[:80])

                # Push to async queue (non-blocking)
                try:
                    loop.call_soon_threadsafe(
                        msg_queue.put_nowait, msg,
                    )
                except Exception:
                    log.warning("queue full — dropping message from chat %d", msg.chat_id)
                    _send_message(token, msg.chat_id, "⚠️ 繁忙，请稍后重试。", session=_get_session())

        log.info("poller thread stopped")

    # ── Start ──
    poller = threading.Thread(target=_poller_thread, daemon=True, name="tg-poller")
    poller.start()

    log.info("starting asyncio worker loop (queue maxsize=%d)...", msg_queue.maxsize)
    log.info("press Ctrl+C to stop")

    try:
        asyncio.run(_worker_loop())
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        poller.join(timeout=5.0)
        _get_session().close()
        log.info("telegram bot stopped")


# ---------------------------------------------------------------------------
# start — 后台启动
# ---------------------------------------------------------------------------

def cmd_start(token: str) -> int:
    """Daemonize: fork child that runs the polling loop."""
    existing = _read_pid()
    if existing is not None and _is_running(existing):
        log.error("telegram bot already running (pid=%d). Use 'restart' to reload.", existing)
        return 1

    orphans = [p for p in _find_orphans() if p != existing]
    if orphans:
        log.warning(
            "found %d orphan telegram_bot process(es): %s",
            len(orphans), orphans,
        )

    log_path = _log_file()
    pid_file = _pid_file()

    cmd = [
        sys.executable, __file__, "run",
        "--token", token,
    ]
    log.info("starting telegram bot daemon, log: %s", log_path)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=log_path.open("ab"),
            stderr=subprocess.STDOUT,
            close_fds=True,
        )
    except OSError as e:
        log.error("failed to start telegram bot: %s", e)
        return 1

    _write_pid(proc.pid)
    log.info("telegram bot starting (pid=%d)...", proc.pid)

    if proc.poll() is not None:
        log.error("telegram bot exited immediately, check log: %s", log_path)
        return 1

    waited = 0.0
    while waited < 3.0:
        new_pid = _read_pid()
        if new_pid is not None and _is_running(new_pid):
            log.info("telegram bot started (pid=%d)", new_pid)
            return 0
        time.sleep(0.2)
        waited += 0.2

    log.error("telegram bot start timed out, check log: %s", log_path)
    return 1


# ---------------------------------------------------------------------------
# stop — 停止后台进程
# ---------------------------------------------------------------------------

def cmd_stop(_args: argparse.Namespace | None = None) -> int:
    pid = _read_pid()
    killed: list[int] = []
    current_pid = os.getpid()

    # Phase 1: kill PID from pid file
    if pid is not None:
        if _is_running(pid):
            log.info("stopping telegram bot (pid=%d)...", pid)
            if _daemon_terminate_pid(pid):
                killed.append(pid)
                log.info("telegram bot stopped (pid=%d)", pid)
            else:
                log.error("failed to kill pid=%d", pid)
        else:
            log.info("stale pid file (pid=%d not running), removing", pid)
        _remove_pid()
    else:
        log.info("no pid file")

    # Phase 2: find and kill orphan telegram_bot processes
    exclude_pids = {current_pid}
    if pid is not None:
        exclude_pids.add(pid)
    orphans = [p for p in _find_orphans() if p not in exclude_pids]
    if orphans:
        log.warning("found %d orphan telegram_bot process(es): %s", len(orphans), orphans)
        for opid in orphans:
            log.info("killing orphan telegram bot pid=%d", opid)
            if _daemon_terminate_pid(opid):
                killed.append(opid)
            else:
                log.error("failed to kill orphan pid=%d", opid)

    # Phase 3: aggressive fallback — taskkill by window title (telegram_bot)
    if not killed:
        try:
            import subprocess
            proc = subprocess.run(
                ["taskkill", "/F", "/FI", "WINDOWTITLE eq *telegram_bot*"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0:
                log.info("aggressive cleanup: killed telegram_bot window processes")
        except Exception:
            pass

    if not killed and pid is None and not orphans:
        log.info("telegram bot not running")
    return 0


# ---------------------------------------------------------------------------
# status — 查看后台状态
# ---------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> int:
    pid = _read_pid()
    running = False
    if pid is None:
        print("telegram_bot: not running (no pid file)")
    elif not _is_running(pid):
        print("telegram_bot: not running (stale pid file, pid=%d)" % pid)
    else:
        cmdline = _daemon_read_pid_cmdline(pid)
        print("telegram_bot: running (pid=%d)" % pid)
        print("  cmdline: %s" % cmdline)
        print("  log:     %s" % _log_file())
        print("  pidfile: %s" % _pid_file())
        running = True

    exclude_pids = {os.getpid()}
    if pid is not None:
        exclude_pids.add(pid)
    orphans = [p for p in _find_orphans() if p not in exclude_pids]
    if orphans:
        print("")
        if running:
            print("⚠ found %d orphan telegram_bot process(es) not tracked by pid file:" % len(orphans))
        else:
            print("⚠ found %d orphan telegram_bot process(es) (pid file missing or stale):" % len(orphans))
        for opid in orphans:
            cmd = _daemon_read_pid_cmdline(opid)
            print("  pid %d  %s" % (opid, cmd))
        return 2 if not running else 0

    return 0 if running else 1


# ---------------------------------------------------------------------------
# restart — 重启后台进程
# ---------------------------------------------------------------------------

def cmd_restart(token: str) -> int:
    log.info("restarting telegram bot...")
    cmd_stop(None)
    # Wait a moment for port cleanup
    time.sleep(1.0)
    return cmd_start(token)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Telegram bot daemon for ai-agent-core.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="前台运行（调试用）")
    _add_common_args(p_run)

    p_start = sub.add_parser("start", help="后台启动守护进程")
    _add_common_args(p_start)

    sub.add_parser("stop", help="停止后台进程")

    p_restart = sub.add_parser("restart", help="重启后台进程")
    _add_common_args(p_restart)

    sub.add_parser("status", help="查看后台状态")

    args = parser.parse_args()

    if args.command is None:
        args.command = "run"
        setattr(args, "token", None)

    cmd = args.command

    # stop / status 不需要 token
    if cmd in ("stop", "status"):
        if cmd == "stop":
            return cmd_stop(args)
        if cmd == "status":
            return cmd_status(args)

    token = _resolve_token(getattr(args, "token", None))

    if cmd == "run":
        return cmd_run(token)
    if cmd == "start":
        return cmd_start(token)
    if cmd == "restart":
        return cmd_restart(token)
    parser.error(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
