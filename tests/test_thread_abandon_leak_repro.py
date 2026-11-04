"""Repro: per-cycle ThreadPoolExecutor + timeout abandon (mirrors resolver/pick schedulers).

Run: pytest tests/test_thread_abandon_leak_repro.py -v -s
Documents overlapping orphan pool threads under rapid abandons (stdlib mirror of production pattern).
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from internal.process_memory import read_rss_kb


def _count_resolver_like_threads() -> int:
    return sum(
        1
        for t in threading.enumerate()
        if t.name.startswith("resolver-cycle-work")
    )


def _abandon_cycle(*, work_seconds: float, timeout_seconds: float) -> None:
    """Minimal copy of resolver_scheduler._run_refresh_cycle_with_timeout abandon path."""
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="resolver-cycle-work")

    def _slow() -> None:
        time.sleep(work_seconds)

    fut = pool.submit(_slow)
    try:
        fut.result(timeout=timeout_seconds)
    except FuturesTimeoutError:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _rapid_abandon_overlap_peak(*, cycles: int) -> int:
    """Fire `cycles` abandons faster than work duration; return peak named worker count."""
    peak_named = 0
    work_seconds = 1.0
    timeout_seconds = 0.01
    spacing_seconds = 0.02
    for _ in range(cycles):
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="resolver-cycle-work")
        fut = pool.submit(time.sleep, work_seconds)
        try:
            fut.result(timeout=timeout_seconds)
        except FuturesTimeoutError:
            pass
        pool.shutdown(wait=False, cancel_futures=True)
        peak_named = max(peak_named, _count_resolver_like_threads())
        time.sleep(spacing_seconds)
    return peak_named


def test_abandon_cycles_increase_thread_count_and_rss():
    baseline_threads = threading.active_count()
    baseline_named = _count_resolver_like_threads()
    baseline_rss = read_rss_kb() or 0

    cycles = 8
    for _ in range(cycles):
        _abandon_cycle(work_seconds=2.0, timeout_seconds=0.05)

    # Orphan pool workers finish their sleep then exit; thread objects linger briefly.
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if _count_resolver_like_threads() == 0:
            break
        time.sleep(0.1)

    after_threads = threading.active_count()
    after_named = _count_resolver_like_threads()
    after_rss = read_rss_kb() or 0

    thread_delta = after_threads - baseline_threads
    rss_delta_kb = after_rss - baseline_rss

    print(
        f"baseline threads={baseline_threads} rss_kb={baseline_rss} "
        f"named_workers={baseline_named}"
    )
    print(
        f"after {cycles} sequential abandon cycles: threads={after_threads} (+{thread_delta}) "
        f"rss_kb={after_rss} (+{rss_delta_kb}) named_workers={after_named}"
    )

    peak_named = _rapid_abandon_overlap_peak(cycles=cycles)
    print(
        f"peak concurrent resolver-cycle-work threads during rapid abandons={peak_named} "
        f"(cycles={cycles})"
    )

    # Must fail if abandons do not overlap (e.g. shutdown(wait=True) or instant work).
    assert peak_named >= cycles, (
        "expected one live orphan per rapid abandon cycle while work outlives timeout; "
        f"peak_named={peak_named} cycles={cycles}"
    )
