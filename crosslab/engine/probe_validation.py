"""
Local process validation for REPORT_INSTRUMENTATION_READY payloads.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

START_TIME_TOLERANCE_S = 2.0


def is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def get_process_start_time(pid: int) -> Optional[float]:
    if pid <= 0:
        return None
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        try:
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                return None
            # FILETIME is 100-ns intervals since 1601-01-01 UTC
            ticks = (creation.dwHighDateTime << 32) + creation.dwLowDateTime
            # Convert to Unix epoch seconds (11644473600 = seconds from 1601 to 1970)
            return (ticks / 10_000_000) - 11644473600
        finally:
            kernel32.CloseHandle(handle)
    proc_stat = f"/proc/{pid}/stat"
    try:
        with open(proc_stat, encoding="utf-8") as f:
            # Field 22 (1-indexed) is starttime in clock ticks after boot
            parts = f.read().split()
            if len(parts) < 22:
                return None
            starttime_ticks = int(parts[21])
        with open("/proc/uptime", encoding="utf-8") as f:
            uptime_s, _ = f.read().split()
        with open("/proc/stat", encoding="utf-8") as f:
            for line in f:
                if line.startswith("btime "):
                    boot_epoch = int(line.split()[1])
                    hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
                    return boot_epoch + (starttime_ticks / hz)
        return None
    except (OSError, ValueError, IndexError):
        return None


def validate_instrumentation_payload(
    payload: Dict[str, Any],
    *,
    strict: bool = False,
    validate_local_process: bool = True,
) -> Dict[str, Any]:
    """
    Validate instrumentation READY payload.

    Returns dict with keys: ok (bool), reason (str), pid (optional int),
    process_start_time (optional float).
    """
    pid_raw = payload.get("pid")
    if pid_raw is None:
        if strict:
            return {"ok": False, "reason": "missing pid", "pid": None, "process_start_time": None}
        return {"ok": True, "reason": "no pid to validate", "pid": None, "process_start_time": None}

    try:
        pid = int(pid_raw)
    except (TypeError, ValueError):
        return {"ok": False, "reason": f"invalid pid: {pid_raw!r}", "pid": None, "process_start_time": None}

    start_raw = payload.get("process_start_time")
    process_start_time: Optional[float] = None
    if start_raw is not None:
        try:
            process_start_time = float(start_raw)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "reason": f"invalid process_start_time: {start_raw!r}",
                "pid": pid,
                "process_start_time": None,
            }

    if strict and process_start_time is None:
        return {
            "ok": False,
            "reason": "process_start_time required in strict mode",
            "pid": pid,
            "process_start_time": None,
        }

    if not validate_local_process:
        return {
            "ok": True,
            "reason": "remote_peer_unverified",
            "pid": pid,
            "process_start_time": process_start_time,
        }

    if not is_process_alive(pid):
        return {
            "ok": False,
            "reason": f"process {pid} is not running",
            "pid": pid,
            "process_start_time": process_start_time,
        }

    if process_start_time is not None:
        actual_start = get_process_start_time(pid)
        if actual_start is not None:
            delta = abs(actual_start - process_start_time)
            if delta > START_TIME_TOLERANCE_S:
                return {
                    "ok": False,
                    "reason": (
                        f"process_start_time mismatch for pid {pid}: "
                        f"expected ~{process_start_time}, actual ~{actual_start:.3f} (delta {delta:.3f}s)"
                    ),
                    "pid": pid,
                    "process_start_time": process_start_time,
                }

    return {
        "ok": True,
        "reason": "process verified",
        "pid": pid,
        "process_start_time": process_start_time,
    }
