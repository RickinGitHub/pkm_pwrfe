# -*- coding: utf-8 -*-
"""Review cron daemon — periodically runs ReviewSkill per distinct L1.

Schedules a review cycle every REVIEW_CRON_EVERY_HOURS (default 24). Each
cycle: build agent, query graph_index.db for distinct l1 values, invoke
ReviewSkill.execute({op:'review', l1:...}) for each, and write the report
to reviews/YYYYMMDD_HHMMSS_<l1>.md.

Run modes (mirrors background_worker.py / server.py):
    python3 review_cron.py run [options]    # 前台运行（默认）
    python3 review_cron.py start [options]  # 后台启动
    python3 review_cron.py stop
    python3 review_cron.py restart [options]
    python3 review_cron.py status

环境变量：
    REVIEW_CRON_EVERY_HOURS   调度间隔小时（默认 24）
    REVIEW_CRON_PID_FILE      PID 文件路径（默认 memories/review_cron.pid）
    REVIEW_CRON_LOG_FILE      后台日志文件（默认 memories/review_cron.log）
    REVIEW_CRON_POLL_SECONDS  轮询间隔秒（默认 60）
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

logging.basicConfig(
    level=os.environ.get("REVIEW_CRON_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("review_cron")

_DEFAULT_PID_FILE = _HERE / "memories" / "review_cron.pid"
_DEFAULT_LOG_FILE = _HERE / "memories" / "review_cron.log"
_DEFAULT_GRAPH_DB = _HERE / "rag" / "graph_index.db"
_DEFAULT_REVIEWS_DIR = _HERE / "reviews"
_SCRIPT_NAME = "review_cron.py"

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
    return _daemon_pid_file_path("REVIEW_CRON_PID_FILE", _DEFAULT_PID_FILE)


def _log_file() -> Path:
    return Path(os.environ.get("REVIEW_CRON_LOG_FILE", _DEFAULT_LOG_FILE))


def _read_pid() -> int | None:
    return _daemon_read_pid("REVIEW_CRON_PID_FILE", _DEFAULT_PID_FILE)


def _write_pid(pid: int) -> None:
    _daemon_write_pid("REVIEW_CRON_PID_FILE", _DEFAULT_PID_FILE, pid)


def _remove_pid() -> None:
    _daemon_remove_pid("REVIEW_CRON_PID_FILE", _DEFAULT_PID_FILE)


def _is_running(pid: int) -> bool:
    return _daemon_is_running(pid)


def _find_orphans(exclude: int | None = None) -> list[int]:
    return _daemon_find_orphan_pids(_SCRIPT_NAME, exclude=exclude)


def _next_run(every_hours: float, now: float | None = None) -> float:
    base = now if now is not None else time.time()
    if every_hours <= 0:
        return base
    return base + every_hours * 3600.0


def _list_distinct_l1(graph_db: Path) -> list[str]:
    if not graph_db.exists():
        log.warning("graph db not found: %s", graph_db)
        return []
    conn = sqlite3.connect(str(graph_db))
    try:
        cur = conn.execute("SELECT DISTINCT l1 FROM document_graph ORDER BY l1")
        return [r[0] for r in cur.fetchall() if r[0]]
    finally:
        conn.close()


def _run_cycle(reviews_dir: Path, graph_db: Path) -> int:
    """Run one review cycle: for each distinct l1, invoke ReviewSkill.

    Returns the number of reports written.
    """
    from harness.factory import build_agent

    l1s = _list_distinct_l1(graph_db)
    if not l1s:
        log.warning("no l1 categories found in %s, skipping cycle", graph_db)
        return 0

    log.info("running review cycle for %d l1(s): %s", len(l1s), l1s)
    agent = build_agent()
    review_skill = agent._skills.get("review")
    if review_skill is None:
        log.error("review skill not registered on agent")
        return 0

    reviews_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    written = 0
    for l1 in l1s:
        safe = l1.replace("/", "_").replace(" ", "_")
        report_path = reviews_dir / f"{timestamp}_{safe}.md"
        log.info("reviewing l1=%s → %s", l1, report_path)
        out = review_skill.execute({
            "op": "review",
            "l1": l1,
            "graph_db_path": str(graph_db),
        })
        if not out.get("ok"):
            log.error("review failed for l1=%s: %s", l1, out.get("error"))
            report_path.write_text(
                f"# Review FAILED for {l1}\n\nError: {out.get('error')}\n",
                encoding="utf-8",
            )
            continue
        result = out.get("result", {}) or {}
        report = result.get("report", "")
        report_path.write_text(
            f"# Review: {l1}\n\n{report}\n",
            encoding="utf-8",
        )
        written += 1
        log.info("wrote %s (chars=%d)", report_path, len(report))
    return written


def run_forever(every_hours: float, poll_seconds: int, stop_event: threading.Event) -> int:
    existing = _read_pid()
    if existing is not None and _is_running(existing):
        log.error("review_cron already running (pid=%d)", existing)
        return 1
    if existing is not None:
        log.warning("stale pid file (pid=%d not running), cleaning up", existing)
        _remove_pid()

    graph_db = Path(os.environ.get("GRAPH_DB_PATH", str(_DEFAULT_GRAPH_DB)))
    reviews_dir = Path(os.environ.get("REVIEWS_DIR", str(_DEFAULT_REVIEWS_DIR)))

    _write_pid(os.getpid())
    log.info("review_cron started (pid=%d, every=%sh, poll=%ss, graph=%s)",
             os.getpid(), every_hours, poll_seconds, graph_db)

    next_run_ts = _next_run(every_hours)
    log.info("first run scheduled at %s", datetime.fromtimestamp(next_run_ts).isoformat())

    try:
        while not stop_event.is_set():
            now = time.time()
            if now >= next_run_ts:
                try:
                    count = _run_cycle(reviews_dir, graph_db)
                    log.info("cycle complete: %d reports written", count)
                except Exception as e:
                    log.error("cycle crashed: %s: %s", type(e).__name__, e)
                next_run_ts = _next_run(every_hours, now=now)
                log.info("next run at %s", datetime.fromtimestamp(next_run_ts).isoformat())
            stop_event.wait(poll_seconds)
    finally:
        _remove_pid()
        log.info("shutdown complete")
    return 0


def cmd_run(every_hours: float, poll_seconds: int) -> int:
    stop_event = threading.Event()

    def _stop(*_: Any) -> None:
        log.info("stop signal received")
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    return run_forever(every_hours, poll_seconds, stop_event)


def _build_run_argv(every_hours: float, poll_seconds: int) -> list[str]:
    return [sys.executable, str(_HERE / _SCRIPT_NAME), "run",
            "--every-hours", str(every_hours),
            "--poll-seconds", str(poll_seconds)]


def cmd_start(every_hours: float, poll_seconds: int) -> int:
    pid = _read_pid()
    if pid is not None and _is_running(pid):
        log.error("review_cron already running (pid=%d)", pid)
        return 1
    if pid is not None:
        log.warning("stale pid file (pid=%d not running), cleaning up", pid)
        _remove_pid()

    log_path = _log_file()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    argv = _build_run_argv(every_hours, poll_seconds)
    log.info("starting review_cron: %s", " ".join(argv))
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
        log.error("review_cron exited immediately, check log: %s", log_path)
        return 1

    waited = 0.0
    while waited < 3.0:
        new_pid = _read_pid()
        if new_pid is not None and _is_running(new_pid):
            log.info("review_cron started (pid=%d)", new_pid)
            return 0
        time.sleep(0.2)
        waited += 0.2

    log.error("review_cron start timed out, check log: %s", log_path)
    return 1


def cmd_stop(_args: argparse.Namespace | None = None) -> int:
    pid = _read_pid()
    killed: list[int] = []

    if pid is not None:
        if _is_running(pid):
            log.info("stopping review_cron (pid=%d)...", pid)
            if _daemon_terminate_pid(pid):
                killed.append(pid)
                log.info("review_cron stopped (pid=%d)", pid)
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
        log.warning("found %d orphan review_cron(s): %s", len(orphans), orphans)
        for opid in orphans:
            if _daemon_terminate_pid(opid):
                killed.append(opid)
            else:
                log.error("failed to kill orphan pid=%d", opid)

    if not killed and pid is None and not orphans:
        log.info("review_cron not running")
    return 0


def cmd_status(_args: argparse.Namespace | None = None) -> int:
    pid = _read_pid()
    running = False
    if pid is None:
        print("review_cron: not running (no pid file)")
    elif not _is_running(pid):
        print("review_cron: not running (stale pid file, pid=%d)" % pid)
    else:
        cmdline = _daemon_read_pid_cmdline(pid)
        print("review_cron: running (pid=%d)" % pid)
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
            print("⚠ found %d orphan review_cron(s):" % len(orphans))
        else:
            print("⚠ found %d orphan review_cron(s) (pid file missing or stale):" % len(orphans))
        for opid in orphans:
            cmd = _daemon_read_pid_cmdline(opid)
            print("  pid %d  %s" % (opid, cmd))
        return 2 if not running else 0

    return 0 if running else 1


def cmd_restart(every_hours: float, poll_seconds: int) -> int:
    log.info("restarting review_cron...")
    cmd_stop(None)
    time.sleep(0.5)
    return cmd_start(every_hours, poll_seconds)


def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--every-hours", type=float,
                   default=float(os.environ.get("REVIEW_CRON_EVERY_HOURS", "24")),
                   help="调度间隔小时（默认读 REVIEW_CRON_EVERY_HOURS 或 24）")
    p.add_argument("--poll-seconds", type=int,
                   default=int(os.environ.get("REVIEW_CRON_POLL_SECONDS", "60")),
                   help="轮询间隔秒（默认 60）")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Review cron daemon: periodic per-l1 review reports.",
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
        args.every_hours = float(os.environ.get("REVIEW_CRON_EVERY_HOURS", "24"))
        args.poll_seconds = int(os.environ.get("REVIEW_CRON_POLL_SECONDS", "60"))

    cmd = args.command
    if cmd == "run":
        return cmd_run(args.every_hours, args.poll_seconds)
    if cmd == "start":
        return cmd_start(args.every_hours, args.poll_seconds)
    if cmd == "stop":
        return cmd_stop(args)
    if cmd == "restart":
        return cmd_restart(args.every_hours, args.poll_seconds)
    if cmd == "status":
        return cmd_status(args)
    parser.error(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
