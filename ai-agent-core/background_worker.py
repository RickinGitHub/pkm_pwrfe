# -*- coding: utf-8 -*-
"""Background file-system watcher for the knowledge base.

Monitors rag/corpus/ (configurable via WATCHER_DIR) for new/modified .md
files and triggers scripts.pipeline_worker.process_file on each. Debounces
rapid duplicate events; serializes processing via a single-worker pool so
config/index.yaml writes don't race.

Run modes:
    python3 background_worker.py run [options]    # 前台运行（默认）
    python3 background_worker.py start [options]  # 后台启动（写 PID 到 .watcher.pid）
    python3 background_worker.py stop             # 停止后台进程（SIGTERM）
    python3 background_worker.py restart [options]  # 重启后台进程
    python3 background_worker.py status           # 查看后台进程状态

环境变量：
    WATCHER_DIR          监控目录（默认 rag/corpus）
    WATCHER_DEBOUNCE_MS  防抖毫秒（默认 500）
    WATCHER_LOG_LEVEL    日志级别（默认 INFO）
    WATCHER_PID_FILE     PID 文件路径（默认 ./.watcher.pid）
    WATCHER_LOG_FILE     后台日志文件（默认 ./.watcher.log）
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

load_dotenv()

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from scripts.pipeline_worker import process_file, delete_file_indexes  # noqa: E402

logging.basicConfig(
    level=os.environ.get("WATCHER_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("watcher")


_IGNORE_PREFIXES = (".", "_")  # hidden + temp; _test.md still processed on demand
_IGNORE_SUFFIXES = (".tmp", ".partial", ".swp", ".bak")
_VALID_SUFFIX = ".md"

# PID/log 文件默认放在项目根（ai-agent-core/）
_DEFAULT_PID_FILE = _HERE / ".watcher.pid"
_DEFAULT_LOG_FILE = _HERE / ".watcher.log"


class DebouncedMdHandler(FileSystemEventHandler):
    """Debounces create/modify events per-path; only .md, skips temp/hidden."""

    def __init__(
        self,
        debounce_ms: int,
        executor: ThreadPoolExecutor,
    ):
        super().__init__()
        self._debounce = debounce_ms / 1000.0
        self._executor = executor
        self._timers: dict[str, threading.Timer] = {}
        self._timers_lock = threading.Lock()

    def _should_handle(self, src_path: str) -> bool:
        p = Path(src_path)
        if p.is_dir():
            return False
        if p.suffix.lower() != _VALID_SUFFIX:
            return False
        name = p.name
        if any(name.startswith(prefix) for prefix in _IGNORE_PREFIXES):
            pass
        if any(name.endswith(suf) for suf in _IGNORE_SUFFIXES):
            return False
        if name == ".gitkeep":
            return False
        return True

    def _schedule(self, src_path: str) -> None:
        with self._timers_lock:
            existing = self._timers.get(src_path)
            if existing is not None:
                existing.cancel()
            timer = threading.Timer(self._debounce, self._dispatch, args=(src_path,))
            timer.daemon = True
            self._timers[src_path] = timer
        timer.start()

    def _dispatch(self, src_path: str) -> None:
        with self._timers_lock:
            self._timers.pop(src_path, None)
        try:
            with open(src_path, "r", encoding="utf-8"):
                pass
        except (OSError, PermissionError) as e:
            log.warning("file not ready (%s): %s — retrying once", src_path, e)
            time.sleep(0.2)
            try:
                with open(src_path, "r", encoding="utf-8"):
                    pass
            except (OSError, PermissionError) as e2:
                log.error("file still locked, skipping: %s (%s)", src_path, e2)
                return
        self._executor.submit(self._process, src_path)

    def _process(self, src_path: str) -> None:
        log.info("processing %s", src_path)
        out = process_file(Path(src_path))
        if out["ok"]:
            r = out["result"]
            log.info(
                "OK %s → %s/%s/%s (chars=%d, graph_added=%s)",
                src_path, r["l1"], r["l2"], r["l3"], r["chars"], r.get("graph_added", r["index_yaml_added"]),
            )
        else:
            log.error("FAIL %s: %s", src_path, out["error"])

    def _process_delete(self, src_path: str) -> None:
        """Phase 3: on_deleted 事件 → 同步清理 FTS5 + graph_index + chunks。"""
        log.info("deleting %s from indexes", src_path)
        out = delete_file_indexes(Path(src_path))
        if out["ok"]:
            r = out["result"]
            log.info(
                "DELETED %s (fts_rows=%d, graph_rows=%d, chunks=%d)",
                src_path, r["fts_deleted"], r["graph_deleted"], r.get("chunks_deleted", 0),
            )
        else:
            log.error("DELETE FAIL %s: %s", src_path, out["error"])

    def on_created(self, event: Any) -> None:
        if event.is_directory:
            return
        if self._should_handle(event.src_path):
            self._schedule(event.src_path)

    def on_modified(self, event: Any) -> None:
        if event.is_directory:
            return
        if self._should_handle(event.src_path):
            self._schedule(event.src_path)

    def on_deleted(self, event: Any) -> None:
        """Phase 3: 文件删除 → 异步清理 FTS5 + graph_index 残留。"""
        if event.is_directory:
            return
        if self._should_handle(event.src_path):
            self._executor.submit(self._process_delete, event.src_path)


# ---------------------------------------------------------------------------
# PID / 进程管理辅助 — 薄封装，委托给 harness.daemon（三处复用：watcher/server/cron）
# ---------------------------------------------------------------------------

from harness.daemon import (
    pid_file_path as _daemon_pid_file_path,
    read_pid as _daemon_read_pid,
    write_pid as _daemon_write_pid,
    remove_pid as _daemon_remove_pid,
    is_running as _daemon_is_running,
    read_pid_cmdline as _daemon_read_pid_cmdline,
    find_orphan_pids as _daemon_find_orphan_pids,
    terminate_pid as _daemon_terminate_pid,
)

_SCRIPT_NAME = "background_worker.py"


def _pid_file_path() -> Path:
    return _daemon_pid_file_path("WATCHER_PID_FILE", _DEFAULT_PID_FILE)


def _log_file_path() -> Path:
    return Path(os.environ.get("WATCHER_LOG_FILE", _DEFAULT_LOG_FILE))


def _read_pid() -> int | None:
    return _daemon_read_pid("WATCHER_PID_FILE", _DEFAULT_PID_FILE)


def _write_pid(pid: int) -> None:
    _daemon_write_pid("WATCHER_PID_FILE", _DEFAULT_PID_FILE, pid)


def _remove_pid() -> None:
    _daemon_remove_pid("WATCHER_PID_FILE", _DEFAULT_PID_FILE)


def _is_running(pid: int) -> bool:
    return _daemon_is_running(pid)


def _read_pid_cmdline(pid: int) -> str:
    return _daemon_read_pid_cmdline(pid)


def _find_orphan_watcher_pids(exclude: int | None = None) -> list[int]:
    """扫进程表找出所有 background_worker.py 运行中的 watcher 进程。

    委托给 harness.daemon.find_orphan_pids，保留原函数名以避免 call site 改动。
    """
    return _daemon_find_orphan_pids(_SCRIPT_NAME, exclude=exclude)


# ---------------------------------------------------------------------------
# 主运行循环（前台）
# ---------------------------------------------------------------------------

def run_forever(watch_dir: Path, debounce_ms: int) -> int:
    """前台运行 watcher，直到收到 SIGINT/SIGTERM。"""
    if not watch_dir.exists():
        log.error("watch dir does not exist: %s", watch_dir)
        return 1

    # 防止重复启动：检查 PID 文件
    existing_pid = _read_pid()
    if existing_pid is not None and _is_running(existing_pid):
        log.error("watcher already running (pid=%d). Stop it first or use 'restart'.", existing_pid)
        return 1
    if existing_pid is not None:
        log.warning("stale pid file found (pid=%d not running), removing", existing_pid)
        _remove_pid()

    observer = Observer()
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pipeline")
    handler = DebouncedMdHandler(debounce_ms=debounce_ms, executor=executor)

    observer.schedule(handler, str(watch_dir), recursive=True)
    observer.start()
    log.info("watching %s (recursive=True, debounce=%dms, pid=%d)",
             watch_dir, debounce_ms, os.getpid())

    _write_pid(os.getpid())

    stop_event = threading.Event()

    def _stop(*_: Any) -> None:
        log.info("stop signal received")
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        stop_event.wait()
    finally:
        observer.stop()
        observer.join(timeout=5.0)
        executor.shutdown(wait=True, cancel_futures=False)
        _remove_pid()
        log.info("shutdown complete")

    return 0


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------

def _build_run_argv(args: argparse.Namespace) -> list[str]:
    """根据 run/start/restart 子命令的参数构造 run 模式的 argv。"""
    argv = [sys.executable, str(_HERE / "background_worker.py"), "run"]
    if args.dir:
        argv += ["--dir", args.dir]
    if args.debounce_ms is not None:
        argv += ["--debounce-ms", str(args.debounce_ms)]
    return argv


def cmd_start(args: argparse.Namespace) -> int:
    """后台启动 watcher：nohup 风格，日志重定向到 WATCHER_LOG_FILE。"""
    pid = _read_pid()
    if pid is not None and _is_running(pid):
        log.error("watcher already running (pid=%d). Use 'restart' to reload.", pid)
        return 1
    if pid is not None:
        log.warning("stale pid file (pid=%d not running), cleaning up", pid)
        _remove_pid()

    log_path = _log_file_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    argv = _build_run_argv(args)
    log.info("starting watcher: %s", " ".join(argv))
    log.info("logs → %s", log_path)

    log_fp = open(log_path, "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            argv,
            stdout=log_fp,
            stderr=log_fp,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # 脱离父进程会话组，不受终端关闭影响
        )
    finally:
        log_fp.close()

    # 等待并校验进程真的起来了
    time.sleep(0.5)
    if proc.poll() is not None:
        log.error("watcher exited immediately, check log: %s", log_path)
        return 1

    # 子进程自己写 PID 文件；这里仅校验
    waited = 0.0
    while waited < 3.0:
        new_pid = _read_pid()
        if new_pid is not None and _is_running(new_pid):
            log.info("watcher started (pid=%d)", new_pid)
            return 0
        time.sleep(0.2)
        waited += 0.2

    log.error("watcher start timed out, check log: %s", log_path)
    return 1


def _terminate_pid(pid: int, deadline_seconds: float = 10.0) -> bool:
    """SIGTERM → 等 → SIGKILL。成功终止返回 True。"""
    return _daemon_terminate_pid(pid, deadline_seconds=deadline_seconds)


def cmd_stop(args: argparse.Namespace) -> int:
    """停止后台 watcher 进程（SIGTERM，超时后 SIGKILL）。

    兜底：扫进程表杀所有 background_worker.py 遗留进程（孤儿）。
    """
    pid = _read_pid()
    killed_pids: list[int] = []

    if pid is not None:
        if _is_running(pid):
            log.info("stopping watcher (pid=%d)...", pid)
            if _terminate_pid(pid):
                killed_pids.append(pid)
                log.info("watcher stopped (pid=%d)", pid)
            else:
                log.error("failed to kill pid=%d", pid)
        else:
            log.info("stale pid file (pid=%d not running), removing", pid)
        _remove_pid()
    else:
        log.info("no pid file")

    # 兜底：扫进程表找出所有遗留 watcher（孤儿进程）。
    # 排除 stop 自身 PID 和 PID 文件已记录的 PID（上面已处理）。
    exclude_pids = {os.getpid()}
    if pid is not None:
        exclude_pids.add(pid)
    orphans = [p for p in _find_orphan_watcher_pids()
               if p not in exclude_pids]
    if orphans:
        log.warning("found %d orphan watcher(s) via process table: %s",
                    len(orphans), orphans)
        for opid in orphans:
            log.info("killing orphan watcher pid=%d", opid)
            if _terminate_pid(opid):
                killed_pids.append(opid)
            else:
                log.error("failed to kill orphan pid=%d", opid)

    if not killed_pids and pid is None and not orphans:
        log.info("watcher not running")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """查看后台 watcher 状态，并报告 PID 文件外的孤儿进程。"""
    pid = _read_pid()
    running = False
    if pid is None:
        print("watcher: not running (no pid file)")
    elif not _is_running(pid):
        print("watcher: not running (stale pid file, pid=%d)" % pid)
    else:
        cmdline = _read_pid_cmdline(pid)
        print("watcher: running (pid=%d)" % pid)
        print("  cmdline: %s" % cmdline)
        print("  log:     %s" % _log_file_path())
        print("  pidfile: %s" % _pid_file_path())
        running = True

    # 兜底：扫进程表报告孤儿进程。
    # 排除 status 自身 PID 和 PID 文件指向的合法 watcher PID。
    exclude_pids = {os.getpid()}
    if pid is not None:
        exclude_pids.add(pid)
    orphans = [p for p in _find_orphan_watcher_pids()
               if p not in exclude_pids]
    if orphans:
        print("")
        if running:
            print("⚠ found %d orphan watcher(s) not tracked by pid file:" % len(orphans))
        else:
            print("⚠ found %d orphan watcher(s) (pid file missing or stale):" % len(orphans))
        for opid in orphans:
            cmd = _read_pid_cmdline(opid)
            print("  pid %d  %s" % (opid, cmd))
        return 2 if not running else 0

    return 0 if running else 1


def cmd_restart(args: argparse.Namespace) -> int:
    """重启 watcher：先 stop 再 start。"""
    log.info("restarting watcher...")
    cmd_stop(args)
    # 等待端口/PID 释放
    time.sleep(0.5)
    return cmd_start(args)


def cmd_run(args: argparse.Namespace) -> int:
    """前台运行 watcher。"""
    watch_dir = Path(args.dir).resolve()
    debounce_ms = args.debounce_ms if args.debounce_ms is not None else int(
        os.environ.get("WATCHER_DEBOUNCE_MS", "500"))
    return run_forever(watch_dir, debounce_ms)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Knowledge base watcher: monitor rag/corpus/ and auto-index .md files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
子命令示例:
  python3 background_worker.py start --dir rag/corpus
  python3 background_worker.py status
  python3 background_worker.py stop
  python3 background_worker.py restart --dir rag/corpus --debounce-ms 500
  python3 background_worker.py run --dir rag/corpus   # 前台运行（默认）
""",
    )
    sub = parser.add_subparsers(dest="command")

    # run（前台）
    p_run = sub.add_parser("run", help="前台运行 watcher（默认模式）")
    _add_common_args(p_run)

    # start（后台）
    p_start = sub.add_parser("start", help="后台启动 watcher（写 PID 文件）")
    _add_common_args(p_start)

    # stop
    p_stop = sub.add_parser("stop", help="停止后台 watcher（SIGTERM，超时 SIGKILL）")

    # restart
    p_restart = sub.add_parser("restart", help="重启后台 watcher")
    _add_common_args(p_restart)

    # status
    p_status = sub.add_parser("status", help="查看后台 watcher 状态")

    args = parser.parse_args()

    # 默认行为：未传子命令时走 run（兼容旧用法）
    if args.command is None:
        args.command = "run"
        args.dir = os.environ.get("WATCHER_DIR", "rag/corpus")
        args.debounce_ms = None

    cmd = args.command
    if cmd == "run":
        return cmd_run(args)
    if cmd == "start":
        return cmd_start(args)
    if cmd == "stop":
        return cmd_stop(args)
    if cmd == "restart":
        return cmd_restart(args)
    if cmd == "status":
        return cmd_status(args)
    parser.error(f"unknown command: {cmd}")
    return 2


def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--dir",
        default=os.environ.get("WATCHER_DIR", "rag/corpus"),
        help="监控目录（相对路径相对于 cwd，默认 rag/corpus）",
    )
    p.add_argument(
        "--debounce-ms",
        type=int,
        default=None,
        help="防抖毫秒（默认读 WATCHER_DEBOUNCE_MS 环境变量或 500）",
    )


if __name__ == "__main__":
    sys.exit(main())

