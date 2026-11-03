"""Resolver scheduler in-place revive (loop stall guard strike 1)."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import wait as futures_wait
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import internal.council.resolver as resolver
import internal.council.resolver_scheduler as rs
import internal.council.weights as weights


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def test_revive_recycles_hung_scheduler_and_runs_once(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    preds = tmp_path / "predictions.json"
    soul.write_text("{}", encoding="utf-8")
    preds.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}), encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.learning.loop_health.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(preds))

    old_tick = _iso(datetime.now(timezone.utc) - timedelta(hours=4))
    soul.write_text(
        json.dumps(
            {
                "prediction_resolver_scheduler": {
                    "last_cycle": {"run_at": old_tick, "ok": True, "pending": 0},
                    "lifecycle": "stopped",
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        rs,
        "_default_subnets",
        lambda: [{"netuid": 1}],
    )
    monkeypatch.setattr(
        resolver,
        "resolve_due_predictions",
        lambda *_a, **_k: {
            "resolved_now": [],
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {"warning": False, "pending_count": 0},
        },
    )
    monkeypatch.setattr(
        resolver,
        "expire_stale_predictions",
        lambda: {
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {"warning": False, "pending_count": 0},
        },
    )

    @contextmanager
    def _free_slot(_name):
        yield True

    monkeypatch.setattr("internal.heavy_job_gate.heavy_job_slot", _free_slot)

    rs.stop_prediction_resolver_scheduler()
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._active = True
    rs._scheduler = sched

    try:
        out = rs.revive_prediction_resolver_scheduler(force=True)
        assert out["recycled"] is True
        assert out["revived"] is True
        assert out["age_after"] is not None
        assert out["age_after"] < 60
        data = json.loads(soul.read_text(encoding="utf-8"))
        last = data["prediction_resolver_scheduler"]["last_cycle"]
        assert last.get("ok") is True
        assert last.get("lifecycle") in ("running", "ticking")
        assert data["prediction_resolver_scheduler"].get("lifecycle") in ("running", "ticking", "starting", "scheduled")
    finally:
        rs.stop_prediction_resolver_scheduler()


def test_revive_honest_when_tick_fresh(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    tick = _iso(datetime.now(timezone.utc))
    soul.write_text(
        json.dumps(
            {"prediction_resolver_scheduler": {"last_cycle": {"run_at": tick, "ok": True}}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.learning.loop_health.SOUL_MAP_PATH", str(soul))
    try:
        out = rs.revive_prediction_resolver_scheduler()
        assert out["revived"] is False
        assert out.get("reason") == "tick_fresh"
    finally:
        rs.stop_prediction_resolver_scheduler()


def test_status_aware_boot_revive_arms_next_run_without_post(tmp_path, monkeypatch):
    """Worker-boot helper arms next_run_at when lifecycle stopped / next_run null."""
    soul = tmp_path / "soul_map.json"
    preds = tmp_path / "predictions.json"
    soul.write_text("{}", encoding="utf-8")
    preds.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}), encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.learning.loop_health.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr(rs, "_default_subnets", lambda: [{"netuid": 1}])
    monkeypatch.setattr(
        resolver,
        "resolve_due_predictions",
        lambda *_a, **_k: {
            "resolved_now": [],
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {"warning": False, "pending_count": 0},
        },
    )
    monkeypatch.setattr(
        resolver,
        "expire_stale_predictions",
        lambda: {
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {"warning": False, "pending_count": 0},
        },
    )

    @contextmanager
    def _free_slot(_name):
        yield True

    monkeypatch.setattr("internal.heavy_job_gate.heavy_job_slot", _free_slot)

    rs.stop_prediction_resolver_scheduler()
    # Simulate post-start hung/stopped: singleton present but next_run_at null.
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._active = False
    sched._lifecycle = "stopped"
    sched._next_run_at = None
    rs._scheduler = sched

    try:
        out = rs.maybe_status_aware_resolver_revive_on_boot()
        state = rs.get_prediction_resolver_scheduler_state()
        assert state.get("next_run_at") is not None or out.get("revived") is True
        # After force revive, scheduler should be active with an armed schedule
        # or have just completed a tick (next_run may be set by _schedule_next).
        armed = rs.get_prediction_resolver_scheduler()
        assert armed is not None
        assert armed._active is True
        assert armed._next_run_at is not None or armed._first_tick_scheduled_at is not None
    finally:
        rs.stop_prediction_resolver_scheduler()


def test_revive_after_cycle_timeout_not_tick_in_progress(tmp_path, monkeypatch):
    """Post-timeout abandon must release cycle_lock so revive can recycle."""
    soul = tmp_path / "soul_map.json"
    preds = tmp_path / "predictions.json"
    soul.write_text("{}", encoding="utf-8")
    preds.write_text(
        json.dumps({"predictions": [], "resolved": [], "stats": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.learning.loop_health.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr(rs, "_default_subnets", lambda: [{"netuid": 1}])
    monkeypatch.setattr(
        resolver,
        "resolve_due_predictions",
        lambda *_a, **_k: {
            "resolved_now": [],
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {"warning": False, "pending_count": 0},
        },
    )
    monkeypatch.setattr(
        resolver,
        "expire_stale_predictions",
        lambda: {
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {"warning": False, "pending_count": 0},
        },
    )

    @contextmanager
    def _free_slot(_name):
        yield True

    monkeypatch.setattr("internal.heavy_job_gate.heavy_job_slot", _free_slot)

    started = threading.Event()
    release = threading.Event()

    def _blocked(self):
        started.set()
        release.wait(timeout=2)
        return {
            "ok": True,
            "run_at": rs._now_iso(),
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
        }

    monkeypatch.setattr(rs, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(rs, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(rs.PredictionResolverScheduler, "_run_refresh_cycle", _blocked)

    old_tick = _iso(datetime.now(timezone.utc) - timedelta(hours=4))
    soul.write_text(
        json.dumps(
            {
                "prediction_resolver_scheduler": {
                    "last_cycle": {"run_at": old_tick, "ok": False, "pending": 0},
                    "lifecycle": "running",
                }
            }
        ),
        encoding="utf-8",
    )

    rs.stop_prediction_resolver_scheduler()
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._active = True
    sched._first_tick_pending = False
    rs._scheduler = sched

    try:
        timed = sched._run_refresh_cycle_with_timeout()
        assert started.wait(timeout=1)
        assert "cycle_timeout" in str(timed.get("error"))
        assert not sched._cycle_lock.locked()
        release.set()

        out = rs.revive_prediction_resolver_scheduler(force=True)
        assert out.get("reason") != "tick_in_progress"
        assert out.get("revived") is True
    finally:
        rs.stop_prediction_resolver_scheduler()


def test_revive_honest_tick_in_progress_when_live_cycle_young(tmp_path, monkeypatch):
    """Young in-flight cycle must still report tick_in_progress."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.learning.loop_health.SOUL_MAP_PATH", str(soul))

    started = threading.Event()
    release = threading.Event()

    def _blocked(self):
        started.set()
        release.wait(timeout=2)
        return {
            "ok": True,
            "run_at": rs._now_iso(),
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
        }

    monkeypatch.setattr(rs, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 30)
    monkeypatch.setattr(rs, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 30)
    monkeypatch.setattr(rs.PredictionResolverScheduler, "_run_refresh_cycle", _blocked)

    tick = _iso(datetime.now(timezone.utc) - timedelta(seconds=30))
    soul.write_text(
        json.dumps(
            {"prediction_resolver_scheduler": {"last_cycle": {"run_at": tick, "ok": True}}}
        ),
        encoding="utf-8",
    )

    rs.stop_prediction_resolver_scheduler()
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._active = True
    sched._first_tick_pending = False
    rs._scheduler = sched

    try:
        threading.Thread(target=sched._run_refresh_cycle_with_timeout, daemon=True).start()
        assert started.wait(timeout=1)
        time.sleep(0.05)
        out = rs.revive_prediction_resolver_scheduler()
        assert out["revived"] is False
        assert out.get("reason") == "tick_in_progress"
        release.set()
    finally:
        rs.stop_prediction_resolver_scheduler()


def test_abandon_frees_wedged_cycle_lock():
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._cycle_lock.acquire()
    sched._lock_owner_gen = sched._cycle_generation
    assert sched._cycle_lock.locked()
    sched._abandon_inflight_cycle()
    assert not sched._cycle_lock.locked()
    assert sched._cycle_lock.acquire(blocking=False)
    sched._cycle_lock.release()


def test_abandon_of_older_generation_keeps_lock_owned_by_current_generation():
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    current = sched._cycle_generation
    sched._cycle_lock.acquire()
    sched._lock_owner_gen = current
    sched._abandon_inflight_cycle(submitted_gen=current - 1)
    assert sched._cycle_lock.locked()
    assert sched._lock_owner_gen == current
    sched._abandon_inflight_cycle(submitted_gen=current)
    assert not sched._cycle_lock.locked()


def test_stale_revive_keeps_lock_a_new_cycle_takes_after_abandon(monkeypatch):
    """Abandon frees the wedged lock; a cycle that takes it in that gap must keep it."""
    monkeypatch.setattr(rs, "_resolver_tick_age_seconds", lambda: 10000.0)
    monkeypatch.setattr(rs, "_resolver_cycle_lock_stale", lambda *a, **k: True)
    rs.stop_prediction_resolver_scheduler()
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._cycle_lock.acquire()
    sched._lock_owner_gen = sched._cycle_generation
    real_abandon = sched._abandon_inflight_cycle

    def abandon_then_new_cycle_takes_lock(**kwargs):
        real_abandon(**kwargs)
        assert sched._cycle_lock.acquire(blocking=False)

    monkeypatch.setattr(sched, "_abandon_inflight_cycle", abandon_then_new_cycle_takes_lock)
    rs._scheduler = sched
    try:
        out = rs.revive_prediction_resolver_scheduler(force=True)
        assert out.get("stale_lock_recycled") is True
        assert sched._cycle_lock.locked()
    finally:
        rs.stop_prediction_resolver_scheduler()


class _OrphanProbe:
    """Blocks the first cycle's resolve call and records which thread runs expire."""

    def __init__(self):
        self.resolve_started = threading.Event()
        self.release = threading.Event()
        self.orphan_thread = None
        self.expire_threads = []
        self._resolve_calls = 0
        self._lock = threading.Lock()

    def resolve(self, *_a, **_k):
        with self._lock:
            self._resolve_calls += 1
            first = self._resolve_calls == 1
        if first:
            self.orphan_thread = threading.current_thread()
            self.resolve_started.set()
            self.release.wait(timeout=5)
        return {
            "resolved_now": [],
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {"warning": False, "pending_count": 0},
        }

    def expire(self):
        self.expire_threads.append(threading.current_thread())
        return {
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {"warning": False, "pending_count": 0},
        }

    def orphan_expires(self):
        return sum(1 for t in self.expire_threads if t is self.orphan_thread)


def _patch_orphan_env(tmp_path, monkeypatch, probe):
    soul = tmp_path / "soul_map.json"
    preds = tmp_path / "predictions.json"
    soul.write_text("{}", encoding="utf-8")
    preds.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}), encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.learning.loop_health.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr(rs, "_default_subnets", lambda: [{"netuid": 1}])
    monkeypatch.setattr(resolver, "resolve_due_predictions", probe.resolve)
    monkeypatch.setattr(resolver, "expire_stale_predictions", probe.expire)

    @contextmanager
    def _free_slot(_name):
        yield True

    monkeypatch.setattr("internal.heavy_job_gate.heavy_job_slot", _free_slot)


def _fresh_scheduler():
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._active = True
    sched._first_tick_pending = False
    rs._scheduler = sched
    return sched


def _start_blocked_cycle(sched, probe):
    """Run one timed cycle in a thread. Return (caller_thread, worker_future) once resolve blocks."""
    caller = threading.Thread(target=sched._run_refresh_cycle_with_timeout, daemon=True)
    caller.start()
    assert probe.resolve_started.wait(timeout=5)
    deadline = time.monotonic() + 5
    while sched._inflight_future is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sched._inflight_future is not None
    return caller, sched._inflight_future


def test_positive_control_orphan_expires_when_nothing_intervenes(tmp_path, monkeypatch):
    """Harness check: an untouched live cycle runs expire on its own worker thread."""
    probe = _OrphanProbe()
    _patch_orphan_env(tmp_path, monkeypatch, probe)
    monkeypatch.setattr(rs, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 30)
    monkeypatch.setattr(rs, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 30)
    rs.stop_prediction_resolver_scheduler()
    sched = _fresh_scheduler()
    try:
        _caller, fut = _start_blocked_cycle(sched, probe)
        probe.release.set()
        futures_wait([fut], timeout=5)
        assert fut.done()
        assert probe.orphan_expires() == 1
    finally:
        probe.release.set()
        rs.stop_prediction_resolver_scheduler()


def test_timed_out_orphan_cannot_expire_after_release(tmp_path, monkeypatch):
    """Timeout path already abandons the cycle, so its late expire stage is skipped."""
    probe = _OrphanProbe()
    _patch_orphan_env(tmp_path, monkeypatch, probe)
    monkeypatch.setattr(rs, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(rs, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 0.2)
    rs.stop_prediction_resolver_scheduler()
    sched = _fresh_scheduler()
    try:
        caller, fut = _start_blocked_cycle(sched, probe)
        caller.join(timeout=5)
        assert not caller.is_alive()
        probe.release.set()
        futures_wait([fut], timeout=5)
        assert fut.done()
        assert probe.orphan_expires() == 0
    finally:
        probe.release.set()
        rs.stop_prediction_resolver_scheduler()


def test_stale_lock_revive_stops_live_orphan_from_expiring(tmp_path, monkeypatch):
    """Revive force-releases a live (not timed-out) cycle; its orphan must not expire afterwards."""
    probe = _OrphanProbe()
    _patch_orphan_env(tmp_path, monkeypatch, probe)
    monkeypatch.setattr(rs, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 30)
    monkeypatch.setattr(rs, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 30)
    monkeypatch.setattr(rs, "_resolver_tick_age_seconds", lambda: 10000.0)
    rs.stop_prediction_resolver_scheduler()
    sched = _fresh_scheduler()
    try:
        _caller, fut = _start_blocked_cycle(sched, probe)
        out = rs.revive_prediction_resolver_scheduler(force=True)
        assert out.get("stale_lock_recycled") is True
        assert out.get("revived") is True
        probe.release.set()
        futures_wait([fut], timeout=5)
        assert fut.done()
        assert probe.orphan_expires() == 0
    finally:
        probe.release.set()
        rs.stop_prediction_resolver_scheduler()

