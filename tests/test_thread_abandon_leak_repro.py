"""Repro: resolver abandon leaves named pool workers (real scheduler path).

Run: pytest tests/test_thread_abandon_leak_repro.py -v -s

Exercises PredictionResolverScheduler._run_refresh_cycle_with_timeout.
Does NOT prove ordinary retry overlap (same scheduler uses _inflight_future guard;
see test_resolver_cycle_timeout_does_not_overlap_inflight_work).

The two-scheduler test is a synthetic multi-instance analogue only — not revive
integration (#1552). Revive overlap belongs in test_resolver_revive.py.

Plan §5 / Ditto fd6a748f: harden concurrent test with baseline named count,
two barrier rendezvous records, peak >= baseline+2, release in finally (next PR).
"""

from __future__ import annotations

import threading
import time

import pytest

from internal.council import resolver_scheduler
from internal.process_memory import read_rss_kb


def _count_resolver_like_threads() -> int:
    return sum(
        1
        for t in threading.enumerate()
        if t.name.startswith("resolver-cycle-work")
    )


def test_resolver_abandon_exposes_named_worker_thread(monkeypatch):
    """Real _run_refresh_cycle_with_timeout: timeout leaves resolver-cycle-work alive."""
    started = threading.Event()
    release = threading.Event()

    def _blocked(self):
        started.set()
        release.wait(timeout=5)
        return {
            "ok": True,
            "run_at": resolver_scheduler._now_iso(),
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
        }

    monkeypatch.setattr(resolver_scheduler, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(
        resolver_scheduler.PredictionResolverScheduler,
        "_run_refresh_cycle",
        _blocked,
    )

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: []
    )
    sched._active = True
    sched._first_tick_pending = False

    baseline_named = _count_resolver_like_threads()
    timed = sched._run_refresh_cycle_with_timeout()
    assert started.wait(timeout=1)
    assert "cycle_timeout" in str(timed.get("error"))

    peak_named = _count_resolver_like_threads()
    assert peak_named >= baseline_named + 1, (
        "expected resolver-cycle-work pool thread while abandoned cycle blocked; "
        f"peak_named={peak_named} baseline_named={baseline_named}"
    )

    release.set()
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if _count_resolver_like_threads() == baseline_named:
            break
        time.sleep(0.05)


def test_two_resolver_schedulers_two_named_workers(monkeypatch):
    """Two scheduler instances concurrently — synthetic overlap analogue, not revive."""
    started = threading.Barrier(2)
    release = threading.Event()

    def _blocked(self):
        started.wait(timeout=2)
        release.wait(timeout=5)
        return {
            "ok": True,
            "run_at": resolver_scheduler._now_iso(),
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
        }

    monkeypatch.setattr(resolver_scheduler, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(
        resolver_scheduler.PredictionResolverScheduler,
        "_run_refresh_cycle",
        _blocked,
    )

    s1 = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: []
    )
    s2 = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: []
    )
    for sched in (s1, s2):
        sched._active = True
        sched._first_tick_pending = False

    peak_holder: dict[str, int] = {"peak": 0}

    def _run(sched: resolver_scheduler.PredictionResolverScheduler) -> None:
        sched._run_refresh_cycle_with_timeout()
        peak_holder["peak"] = max(peak_holder["peak"], _count_resolver_like_threads())

    t1 = threading.Thread(target=_run, args=(s1,), daemon=True)
    t2 = threading.Thread(target=_run, args=(s2,), daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=3)
    t2.join(timeout=3)

    peak_named = max(peak_holder["peak"], _count_resolver_like_threads())
    assert peak_named >= 2, (
        "expected two resolver-cycle-work threads from two concurrent abandoned cycles; "
        f"peak_named={peak_named}"
    )

    release.set()
    time.sleep(0.3)


@pytest.mark.parametrize("cycles", [4])
def test_sequential_abandon_drain_diagnostic(monkeypatch, cycles: int):
    """Print RSS/thread deltas after real abandons that drain — not an accumulation proof."""

    def _slow(self):
        time.sleep(0.25)
        return {
            "ok": True,
            "run_at": resolver_scheduler._now_iso(),
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
        }

    monkeypatch.setattr(resolver_scheduler, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(
        resolver_scheduler.PredictionResolverScheduler,
        "_run_refresh_cycle",
        _slow,
    )

    baseline_threads = threading.active_count()
    baseline_rss = read_rss_kb() or 0

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: []
    )
    sched._active = True
    sched._first_tick_pending = False

    for _ in range(cycles):
        sched._run_refresh_cycle_with_timeout()
        time.sleep(0.35)

    after_threads = threading.active_count()
    after_rss = read_rss_kb() or 0
    print(
        f"sequential real abandons cycles={cycles}: threads +{after_threads - baseline_threads} "
        f"rss_kb +{after_rss - baseline_rss}"
    )
