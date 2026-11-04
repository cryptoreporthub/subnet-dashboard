"""Linux process identity helpers for prod OOM attribution (#1466)."""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional

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
    except (AttributeError, OSError, ValueError, IndexError):
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


# Exact names emitted by the whole-job scopes: pick_scheduler.py heavy_job_rss_scope("daily_pick_scheduler")
# and pump/scheduler.py log_heavy_job_rss("pump_ladder_scan", ...). Sub-stage names such as
# "daily_pick_scheduler:market_context" must NOT match (exact set membership, no prefix match).
_TRIM_AFTER_JOBS = frozenset({"daily_pick_scheduler", "pump_ladder_scan"})


def _read_mallinfo2() -> str:
    """glibc mallinfo2 in KB (arena=brk heap, hblkhd=mmap'd, uordblks=in use, fordblks=free, keepcost=main-arena top chunk only).

    Tells allocator fragmentation (fordblks large) apart from a live object graph (uordblks large).
    mi_keep_main_kb is glibc keepcost: the MAIN arena's top chunk only. It is NOT total trimmable memory
    (other arenas' free tops are not included), so do not read it as "what malloc_trim could return".
    "unknown" on non-glibc, glibc < 2.33 (no mallinfo2) or any ctypes failure.
    """
    try:
        import ctypes

        names = (
            "arena", "ordblks", "smblks", "hblks", "hblkhd",
            "usmblks", "fsmblks", "uordblks", "fordblks", "keepcost",
        )  # fmt: skip

        class _MallInfo2(ctypes.Structure):
            _fields_ = [(n, ctypes.c_size_t) for n in names]

        fn = ctypes.CDLL("libc.so.6").mallinfo2
        fn.restype = _MallInfo2
        mi = fn()
        kb = {n: getattr(mi, n) // 1024 for n in ("arena", "hblkhd", "uordblks", "fordblks", "keepcost")}
        return (
            f"mi_arena_kb={kb['arena']} mi_hblkhd_kb={kb['hblkhd']} mi_uord_kb={kb['uordblks']} "
            f"mi_ford_kb={kb['fordblks']} mi_keep_main_kb={kb['keepcost']}"
        )
    except Exception:
        return "mi_arena_kb=unknown mi_hblkhd_kb=unknown mi_uord_kb=unknown mi_ford_kb=unknown mi_keep_main_kb=unknown"


def _read_mem_breakdown() -> str:
    """End-of-job fields: anon RSS, file-backed PSS, whole-read time (breakdown_ms), thread count, gc counts, glibc mallinfo2, arena cap."""
    # anon_kb is resident anonymous memory (RSS basis). pss_file_kb is Pss_File: the proportional-share
    # of file-backed pages (shared file mappings are prorated), so it is NOT file RSS and is not
    # directly additive with rss_kb.
    parts = []
    t0 = time.perf_counter()
    try:
        with open("/proc/self/smaps_rollup", encoding="utf-8") as handle:
            kb = {
                ln.split(":")[0]: ln.split()[1] for ln in handle if ":" in ln and len(ln.split()) >= 2
            }
        parts.append(f"anon_kb={kb['Anonymous']} pss_file_kb={kb['Pss_File']}")
    except (OSError, KeyError, IndexError, ValueError):  # ValueError incl. UnicodeDecodeError
        parts.append("anon_kb=unknown pss_file_kb=unknown")
    import gc

    parts.append(f"threads={threading.active_count()} gc={'/'.join(map(str, gc.get_count()))}")
    parts.append(_read_mallinfo2())
    # breakdown_ms wraps the WHOLE memory read (smaps_rollup + gc + mallinfo2), so slow reads are visible.
    parts.append(f"breakdown_ms={(time.perf_counter() - t0) * 1000.0:.2f}")
    parts.append(f"arena_max={os.environ.get('MALLOC_ARENA_MAX') or 'unset'}")
    return " ".join(parts)


def _maybe_malloc_trim(name: str) -> None:
    """Env-flagged malloc_trim(0) after the daily pick / pump scan; logs RSS before and after."""
    flag = os.environ.get("MEMORY_MALLOC_TRIM_AFTER_JOBS", "").lower()
    if name not in _TRIM_AFTER_JOBS or flag not in ("1", "true", "yes", "on"):
        return
    try:
        import ctypes

        trim = ctypes.CDLL("libc.so.6").malloc_trim  # glibc only; AttributeError/OSError elsewhere
    except (OSError, AttributeError):
        logger.info("malloc_trim name=%s unavailable (non-glibc)", name)
        return
    before = read_rss_kb()
    released = trim(0)
    logger.info(
        "malloc_trim name=%s rss_before_kb=%s rss_after_kb=%s released=%s",
        name,
        before,
        read_rss_kb(),
        released,
    )


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
        msg = (
            f"heavy_job_rss name={name} phase={phase} run_mode={run_mode} pid={pid} "
            f"rss_kb={'unknown' if rss is None else rss} held_ms={held_ms:.1f}"
        )
        if process_uptime_s is not None:
            msg += f" process_uptime_s={process_uptime_s:.3f}"
        if phase == "end":
            msg += " " + _read_mem_breakdown()
        logger.info(msg)
        if phase == "end":
            _maybe_malloc_trim(name)
    except Exception as exc:
        logger.debug("heavy_job_rss log failed: %s", exc)


@contextmanager
def heavy_job_rss_scope(name: str) -> Iterator[None]:
    """RSS start/end bookends around a block; the end line is logged even if the block raises."""
    t0 = time.perf_counter()
    log_heavy_job_rss(name, "start")
    try:
        yield
    finally:
        log_heavy_job_rss(name, "end", started_at=t0)


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
