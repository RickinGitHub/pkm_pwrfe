# -*- coding: utf-8 -*-
"""HTTP API server for ai-agent-core.

Exposes AgentCore.handle() over FastAPI. AgentCore is NOT thread-safe
(mutates ShortTerm JSON, CacheGuard SQLite, LongTerm SQLite without locks),
so all /query calls are serialized via a process-wide threading.Lock.

Run modes (mirrors background_worker.py):
    python3 server.py run [--port 8000]    # 前台运行（默认）
    python3 server.py start [--port 8000]  # 后台启动（写 PID 到 memories/server.pid）
    python3 server.py stop                 # 停止后台进程
    python3 server.py restart [--port 8000]
    python3 server.py status

环境变量：
    SERVER_PORT           监听端口（默认 8000）
    SERVER_HOST           监听地址（默认 127.0.0.1）
    SERVER_PID_FILE       PID 文件路径（默认 memories/server.pid）
    SERVER_LOG_FILE       后台日志文件（默认 memories/server.log）
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

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from pydantic import BaseModel


_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

logging.basicConfig(
    level=os.environ.get("SERVER_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("server")

_DEFAULT_PID_FILE = _HERE / "memories" / "server.pid"
_DEFAULT_LOG_FILE = _HERE / "memories" / "server.log"
_SCRIPT_NAME = "server.py"

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


def _pid_file() -> Path:
    return _daemon_pid_file_path("SERVER_PID_FILE", _DEFAULT_PID_FILE)


def _log_file() -> Path:
    return Path(os.environ.get("SERVER_LOG_FILE", _DEFAULT_LOG_FILE))


def _read_pid() -> int | None:
    return _daemon_read_pid("SERVER_PID_FILE", _DEFAULT_PID_FILE)


def _write_pid(pid: int) -> None:
    _daemon_write_pid("SERVER_PID_FILE", _DEFAULT_PID_FILE, pid)


def _remove_pid() -> None:
    _daemon_remove_pid("SERVER_PID_FILE", _DEFAULT_PID_FILE)


def _is_running(pid: int) -> bool:
    return _daemon_is_running(pid)


def _find_orphans(exclude: int | None = None) -> list[int]:
    return _daemon_find_orphan_pids(_SCRIPT_NAME, exclude=exclude)


# Lazy-initialized app + agent (so module import doesn't bootstrap the agent).
_app = None
_agent = None
_lock = threading.Lock()
_agent_lock = threading.Lock()


class QueryRequest(BaseModel):
    query: str


def _get_agent():
    global _agent
    if _agent is None:
        with _agent_lock:
            if _agent is None:
                from harness.factory import build_agent
                _agent = build_agent()
    return _agent


def _get_app():
    global _app
    if _app is None:
        app = FastAPI(title="ai-agent-core", version="0.1.0")

        @app.get("/health")
        def health() -> dict:
            return {"ok": True}

        @app.post("/query")
        def query_endpoint(req: QueryRequest) -> dict:
            with _lock:
                return _get_agent().handle(req.query)

        _app = app
    return _app


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------

def cmd_run(port: int, host: str) -> int:
    existing = _read_pid()
    if existing is not None and _is_running(existing):
        log.error("server already running (pid=%d). Use 'restart' to reload.", existing)
        return 1
    if existing is not None:
        log.warning("stale pid file (pid=%d not running), cleaning up", existing)
        _remove_pid()

    import uvicorn
    _write_pid(os.getpid())

    stop_event = threading.Event()

    def _stop(*_: Any) -> None:
        log.info("stop signal received")
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    app = _get_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    def _serve() -> None:
        try:
            server.run()
        except Exception as e:
            log.error("server crashed: %s", e)
            stop_event.set()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()

    log.info("server listening on %s:%d (pid=%d)", host, port, os.getpid())
    try:
        stop_event.wait()
    finally:
        server.should_exit = True
        t.join(timeout=5.0)
        _remove_pid()
        log.info("shutdown complete")
    return 0


def _build_run_argv(port: int, host: str) -> list[str]:
    return [sys.executable, str(_HERE / _SCRIPT_NAME), "run",
            "--port", str(port), "--host", host]


def cmd_start(port: int, host: str) -> int:
    pid = _read_pid()
    if pid is not None and _is_running(pid):
        log.error("server already running (pid=%d). Use 'restart' to reload.", pid)
        return 1
    if pid is not None:
        log.warning("stale pid file (pid=%d not running), cleaning up", pid)
        _remove_pid()

    log_path = _log_file()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    argv = _build_run_argv(port, host)
    log.info("starting server: %s", " ".join(argv))
    log.info("logs → %s", log_path)

    log_fp = open(log_path, "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            argv,
            stdout=log_fp,
            stderr=log_fp,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    finally:
        log_fp.close()

    time.sleep(0.5)
    if proc.poll() is not None:
        log.error("server exited immediately, check log: %s", log_path)
        return 1

    waited = 0.0
    while waited < 3.0:
        new_pid = _read_pid()
        if new_pid is not None and _is_running(new_pid):
            log.info("server started (pid=%d)", new_pid)
            return 0
        time.sleep(0.2)
        waited += 0.2

    log.error("server start timed out, check log: %s", log_path)
    return 1


def cmd_stop(_args: argparse.Namespace | None = None) -> int:
    pid = _read_pid()
    killed: list[int] = []

    if pid is not None:
        if _is_running(pid):
            log.info("stopping server (pid=%d)...", pid)
            if _daemon_terminate_pid(pid):
                killed.append(pid)
                log.info("server stopped (pid=%d)", pid)
            else:
                log.error("failed to kill pid=%d", pid)
        else:
            log.info("stale pid file (pid=%d not running), removing", pid)
        _remove_pid()
    else:
        log.info("no pid file")

    exclude_pids = {os.getpid()}
    if pid is not None:
        exclude_pids.add(pid)
    orphans = [p for p in _find_orphans() if p not in exclude_pids]
    if orphans:
        log.warning("found %d orphan server(s) via process table: %s", len(orphans), orphans)
        for opid in orphans:
            log.info("killing orphan server pid=%d", opid)
            if _daemon_terminate_pid(opid):
                killed.append(opid)
            else:
                log.error("failed to kill orphan pid=%d", opid)

    if not killed and pid is None and not orphans:
        log.info("server not running")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    pid = _read_pid()
    running = False
    if pid is None:
        print("server: not running (no pid file)")
    elif not _is_running(pid):
        print("server: not running (stale pid file, pid=%d)" % pid)
    else:
        cmdline = _daemon_read_pid_cmdline(pid)
        print("server: running (pid=%d)" % pid)
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
            print("⚠ found %d orphan server(s) not tracked by pid file:" % len(orphans))
        else:
            print("⚠ found %d orphan server(s) (pid file missing or stale):" % len(orphans))
        for opid in orphans:
            cmd = _daemon_read_pid_cmdline(opid)
            print("  pid %d  %s" % (opid, cmd))
        return 2 if not running else 0

    return 0 if running else 1


def cmd_restart(port: int, host: str) -> int:
    log.info("restarting server...")
    cmd_stop(None)
    time.sleep(0.5)
    return cmd_start(port, host)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="HTTP API server for ai-agent-core.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="前台运行（默认）")
    _add_common_args(p_run)

    p_start = sub.add_parser("start", help="后台启动")
    _add_common_args(p_start)

    sub.add_parser("stop", help="停止后台进程")
    p_restart = sub.add_parser("restart", help="重启后台进程")
    _add_common_args(p_restart)
    sub.add_parser("status", help="查看后台状态")

    args = parser.parse_args()

    if args.command is None:
        args.command = "run"
        args.port = int(os.environ.get("SERVER_PORT", "8000"))
        args.host = os.environ.get("SERVER_HOST", "127.0.0.1")

    cmd = args.command
    if cmd == "run":
        return cmd_run(args.port, args.host)
    if cmd == "start":
        return cmd_start(args.port, args.host)
    if cmd == "stop":
        return cmd_stop(args)
    if cmd == "restart":
        return cmd_restart(args.port, args.host)
    if cmd == "status":
        return cmd_status(args)
    parser.error(f"unknown command: {cmd}")
    return 2


def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--port", type=int,
                   default=int(os.environ.get("SERVER_PORT", "8000")),
                   help="监听端口（默认读 SERVER_PORT 或 8000）")
    p.add_argument("--host",
                   default=os.environ.get("SERVER_HOST", "127.0.0.1"),
                   help="监听地址（默认读 SERVER_HOST 或 127.0.0.1）")


if __name__ == "__main__":
    sys.exit(main())
