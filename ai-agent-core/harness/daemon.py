# -*- coding: utf-8 -*-
"""Shared daemon helpers: PID file management, signal-based process control,
orphan process discovery. Supports both Windows and Linux (macOS)."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

_IS_WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------------------
# PID file helpers (cross-platform)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Process query helpers
# ---------------------------------------------------------------------------

def is_running(pid: int) -> bool:
    """Check if a process with the given PID is running (cross-platform)."""
    if _IS_WINDOWS:
        return _win_is_running(pid)
    # Unix: signal 0 tests existence without actually sending a signal
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _win_is_running(pid: int) -> bool:
    """Windows: check process existence via tasklist (fast, no extra deps)."""
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True, text=False, timeout=5,
        )
        stdout = proc.stdout
        if stdout is None:
            return False
        # tasklist output uses system locale encoding (e.g. GBK on Chinese Windows)
        try:
            text = stdout.decode("utf-8") if isinstance(stdout, bytes) else str(stdout)
        except UnicodeDecodeError:
            text = stdout.decode("gbk", errors="replace") if isinstance(stdout, bytes) else str(stdout)
        return str(pid) in text
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def read_pid_cmdline(pid: int) -> str:
    """Return the command line of a process (cross-platform)."""
    if _IS_WINDOWS:
        return _win_read_pid_cmdline(pid)
    # Unix: read from /proc/<pid>/cmdline
    try:
        cmdline = Path("/proc") / str(pid) / "cmdline"
        if cmdline.exists():
            return cmdline.read_bytes().decode("utf-8", errors="replace").replace("\x00", " ")
    except OSError:
        pass
    return ""


def _win_read_pid_cmdline(pid: int) -> str:
    """Windows: query process command line via WMI (PowerShell)."""
    try:
        proc = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' "
                f"| Select-Object -ExpandProperty CommandLine",
            ],
            capture_output=True, text=False, timeout=5,
        )
        if proc.returncode == 0 and proc.stdout:
            try:
                return proc.stdout.decode("utf-8", errors="replace").strip()
            except UnicodeDecodeError:
                return proc.stdout.decode("gbk", errors="replace").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""


# ---------------------------------------------------------------------------
# Orphan process discovery
# ---------------------------------------------------------------------------

def find_orphan_pids(script_name: str, exclude: int | None = None) -> list[int]:
    """Find all running python processes executing <script_name>.py.

    Works on both Windows and Unix. Validates cmdline to avoid false matches.
    """
    if _IS_WINDOWS:
        return _win_find_orphan_pids(script_name, exclude)
    return _unix_find_orphan_pids(script_name, exclude)


def _unix_find_orphan_pids(script_name: str, exclude: int | None = None) -> list[int]:
    """Unix: use pgrep -f to find matching processes."""
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


def _win_find_orphan_pids(script_name: str, exclude: int | None = None) -> list[int]:
    """Windows: use tasklist to find matching python processes (fast, no PowerShell)."""
    pids: list[int] = []
    try:
        # tasklist is much faster than PowerShell WMI
        proc = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq python.exe"],
            capture_output=True, text=False, timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return pids
    if proc.returncode != 0 or not proc.stdout:
        return pids

    try:
        text = proc.stdout.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        text = proc.stdout.decode("gbk", errors="replace")

    # tasklist CSV: "python.exe","1234","Console","1","xxx K"
    import re
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 2:
            continue
        pid_str = parts[1].strip('" ')
        try:
            p = int(pid_str)
        except ValueError:
            continue
        if exclude is not None and p == exclude:
            continue
        # We don't have cmdline from tasklist CSV, so just check by PID existence
        # and verify it's actually our script by checking command line
        cmdline = _win_read_pid_cmdline(p)
        if script_name.lower() in cmdline.lower():
            pids.append(p)
    return pids


# ---------------------------------------------------------------------------
# Process termination
# ---------------------------------------------------------------------------

def terminate_pid(pid: int, deadline_seconds: float = 10.0) -> bool:
    """SIGTERM (or TerminateProcess on Windows) → wait → SIGKILL (or force).

    Returns True if the process is confirmed gone.
    """
    if _IS_WINDOWS:
        return _win_terminate_pid(pid, deadline_seconds)

    # Unix: SIGTERM → wait → SIGKILL
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


def _win_terminate_pid(pid: int, deadline_seconds: float = 10.0) -> bool:
    """Windows: use taskkill for graceful → force termination."""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T"],
            capture_output=True, timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    deadline = time.time() + deadline_seconds
    while time.time() < deadline:
        if not is_running(pid):
            return True
        time.sleep(0.3)

    log.warning("pid=%d did not exit in %ss, sending force kill", pid, deadline_seconds)
    try:
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid), "/T"],
            capture_output=True, timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    time.sleep(0.3)
    return not is_running(pid)
