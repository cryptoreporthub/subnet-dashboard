"""Linux process identity helpers for prod OOM attribution (#1466)."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger("process_memory")

_HEARTBEAT_STARTED = False
_PROCESS_START_PERF = time.perf_counter()


def _process_uptime_from_proc() -> Optional[float]:
    """Process age from Linux /proc (None if unreadable)."""
    try:
        clk_tck = os.sysconf("SC_CLK_TCK")
        if clk_tck <= 0:
            return None
        with open("/proc/uptime", encoding="utf-8") as handle:
            system_uptime = float(handle.read().split()[0])
        with open("/proc/self/stat", encoding="utf-8") as handle:
            stat = handle.read()
        rparen = stat.rfind(")")
        if rparen < 0:
            return None
        fields = stat[rparen + 2 :].split()
        if len(fields) <= 19:
            return None
        starttime = int(fields[19])
        return max(0.0, system_uptime - starttime / clk_tck)
    except (OSError, ValueError, IndexError):
        return None


def process_uptime_seconds() -> float:
    """Seconds since this process started (from /proc when available).

    Falls back to monotonic time since ``process_memory`` was first imported when
    /proc is unreadable (e.g. non-Linux).
    """
    proc_age = _process_uptime_from_proc()
    if proc_age is not None:
        return proc_age
    return time.perf_counter() - _PROCESS_START_PERF


def set_linux_process_comm(name: str) -> None:
    """Set the 15-char kernel thread name (visible in OOM killer lines)."""
    title = (name or "")[:15]
    if not title:
        return
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        buf = ctypes.create_string_buffer(title.encode("utf-8", errors="replace")[:15])
        libc.prctl(15, buf, 0, 0, 0)
    except Exception:
        pass


def read_rss_kb(pid: Optional[int] = None) -> Optional[int]:
    target = pid if pid is not None else os.getpid()
    path = f"/proc/{target}/status"
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1])
    except OSError:
        return None
    return None


def log_memory_snapshot(label: str) -> None:
    rss = read_rss_kb()
    if rss is None:
        logger.info("%s pid=%s rss_kb=unknown", label, os.getpid())
        return
    logger.info("%s pid=%s rss_kb=%d", label, os.getpid(), rss)


def log_heavy_job_rss(
    name: str,
    phase: str,
    *,
    started_at: Optional[float] = None,
    process_uptime_s: Optional[float] = None,
) -> None:
    """RSS bookends for heavy jobs (#1538 observability)."""
    try:
        from internal.run_mode import get_run_mode

        run_mode = get_run_mode()
        pid = os.getpid()
        rss = read_rss_kb()
        if phase == "milestone" and process_uptime_s is None:
            process_uptime_s = process_uptime_seconds()
        held_ms = 0.0
        if phase == "end" and started_at is not None:
            held_ms = (time.perf_counter() - started_at) * 1000.0
        uptime_s = process_uptime_s
        if rss is None:
            if uptime_s is not None:
                logger.info(
                    "heavy_job_rss name=%s phase=%s run_mode=%s pid=%s rss_kb=unknown "
                    "held_ms=%.1f process_uptime_s=%.3f",
                    name,
                    phase,
                    run_mode,
                    pid,
                    held_ms,
                    uptime_s,
                )
            else:
                logger.info(
                    "heavy_job_rss name=%s phase=%s run_mode=%s pid=%s rss_kb=unknown held_ms=%.1f",
                    name,
                    phase,
                    run_mode,
                    pid,
                    held_ms,
                )
            return
        if uptime_s is not None:
            logger.info(
                "heavy_job_rss name=%s phase=%s run_mode=%s pid=%s rss_kb=%d held_ms=%.1f "
                "process_uptime_s=%.3f",
                name,
                phase,
                run_mode,
                pid,
                rss,
                held_ms,
                uptime_s,
            )
            return
        logger.info(
            "heavy_job_rss name=%s phase=%s run_mode=%s pid=%s rss_kb=%d held_ms=%.1f",
            name,
            phase,
            run_mode,
            pid,
            rss,
            held_ms,
        )
    except Exception as exc:
        logger.debug("heavy_job_rss log failed: %s", exc)


def _rss_heartbeat_label() -> str:
    if os.environ.get("LIVE_SUBNETS_FETCH_CHILD") == "1":
        return "rss-heartbeat role=live_subnets_fetch_child"
    from internal.run_mode import get_run_mode

    return f"rss-heartbeat run_mode={get_run_mode()}"


def start_rss_heartbeat(interval_seconds: float = 120.0) -> None:
    global _HEARTBEAT_STARTED
    if _HEARTBEAT_STARTED:
        return
    if interval_seconds <= 0:
        return
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CI"):
        return
    label = _rss_heartbeat_label()

    def _loop() -> None:
        while True:
            log_memory_snapshot(label)
            time.sleep(interval_seconds)

    _HEARTBEAT_STARTED = True
    threading.Thread(target=_loop, daemon=True, name="rss-heartbeat").start()
