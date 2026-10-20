"""Linux process identity helpers for prod OOM attribution (#1466)."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger("process_memory")

_HEARTBEAT_STARTED = False


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


def start_rss_heartbeat(interval_seconds: float = 120.0) -> None:
    global _HEARTBEAT_STARTED
    if _HEARTBEAT_STARTED:
        return
    if interval_seconds <= 0:
        return
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CI"):
        return
    if os.environ.get("LIVE_SUBNETS_FETCH_CHILD") == "1":
        label = "rss-heartbeat role=live_subnets_fetch_child"
    else:
        from internal.run_mode import get_run_mode

        label = f"rss-heartbeat run_mode={get_run_mode()}"

    def _loop() -> None:
        while True:
            log_memory_snapshot(label)
            time.sleep(interval_seconds)

    _HEARTBEAT_STARTED = True
    threading.Thread(target=_loop, daemon=True, name="rss-heartbeat").start()
