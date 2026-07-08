# -*- coding: utf-8 -*-
"""Shared daemon helpers: PID file management, signal-based process control,
orphan process discovery via pgrep. Used by background_worker.py, server.py,
and review_cron.py to avoid duplicating the same boilerplate three times."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from pathlib import Path

log = logging.getLogger(__name__)


def pid_file_path(env_var: str, default: Path) -> Path:
    return Path(os.environ.get(env_var, default))


def read_pid(env_var: str, default: Path) -> int | None:
    pf = pid_file_path(env_var, default)
    if not pf.exists():
        return None
    try:
        return int(pf.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def write_pid(env_var: str, default: Path, pid: int) -> None:
    pf = pid_file_path(env_var, default)
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(str(pid), encoding="utf-8")


def remove_pid(env_var: str, default: Path) -> None:
    pf = pid_file_path(env_var, default)
    if pf.exists():
        try:
            pf.unlink()
        except OSError:
            pass


def is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid_cmdline(pid: int) -> str:
    try:
        cmdline = Path("/proc") / str(pid) / "cmdline"
        if cmdline.exists():
            return cmdline.read_bytes().decode("utf-8", errors="replace").replace("\x00", " ")
    except OSError:
        pass
    return ""


def find_orphan_pids(script_name: str, exclude: int | None = None) -> list[int]:
    """Find all running python processes executing <script_name>.py.

    Validates cmdline so shell wrappers are not mistaken for the daemon.
    """
    pids: list[int] = []
    try:
        proc = subprocess.run(
            ["pgrep", "-f", script_name],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return pids
    if proc.returncode != 0:
        return pids

    for line in proc.stdout.split():
        line = line.strip()
        if not line.isdigit():
            continue
        p = int(line)
        if exclude is not None and p == exclude:
            continue
        cmdline = read_pid_cmdline(p)
        if not cmdline:
            continue
        parts = cmdline.split()
        if len(parts) < 2:
            continue
        interpreter = parts[0].lower()
        script = parts[1]
        if "python" not in interpreter:
            continue
        if not (script.endswith(script_name) or script_name in script):
            continue
        pids.append(p)
    return pids


def terminate_pid(pid: int, deadline_seconds: float = 10.0) -> bool:
    """SIGTERM → wait → SIGKILL. Returns True if the process is gone."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError as e:
        log.error("no permission to signal pid=%d: %s", pid, e)
        return False

    deadline = time.time() + deadline_seconds
    while time.time() < deadline:
        if not is_running(pid):
            return True
        time.sleep(0.3)

    log.warning("pid=%d did not exit in %ss, sending SIGKILL", pid, deadline_seconds)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    time.sleep(0.3)
    return not is_running(pid)
