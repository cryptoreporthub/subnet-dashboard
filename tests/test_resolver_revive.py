"""Resolver scheduler in-place revive (loop stall guard strike 1)."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import wait as futures_wait
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

import internal.council.resolver as resolver
import internal.council.resolver_scheduler as rs
import internal.council.weights as weights
from internal import liveness
from internal.learning import loop_health


@pytest.fixture(autouse=True)
def _fresh_resolver_liveness_cache():
    loop_health._RESOLVER_LIVENESS_CACHE.update({"at": 0.0, "payload": None, "seq": -1})
    loop_health._RESOLVER_LIVENESS_BUILDING = False
    yield
    loop_health._RESOLVER_LIVENESS_CACHE.update({"at": 0.0, "payload": None, "seq": -1})
    loop_health._RESOLVER_LIVENESS_BUILDING = False


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
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.learning.loop_health.SOUL_MAP_PATH", str(soul))
    monkeypatch.setitem(liveness._REGISTRY, "prediction_resolver", None)
    tracker = liveness.LivenessTracker("prediction_resolver", 60, persist=False)
    tracker.record_success({"noop": True})
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


def test_stale_revive_keeps_lock_a_new_cycle_takes_after_abandon(tmp_path, monkeypatch):
    """Abandon frees the wedged lock; a cycle that takes it in that gap must keep it."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.learning.loop_health.SOUL_MAP_PATH", str(soul))
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


def test_zero_budget_cycle_then_revive_submitted_gen_matches_owner(
    tmp_path, monkeypatch
):
    """Ditto P3-R4: after zero-budget bump, revive abandon uses current _lock_owner_gen."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.learning.loop_health.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(rs, "_resolver_tick_age_seconds", lambda: 10000.0)
    monkeypatch.setattr(rs, "_resolver_cycle_lock_stale", lambda *a, **k: True)

    def _quick_cycle(self):
        return {"ok": True, "resolved_now": 0, "expired_now": 0, "pending": 0}

    monkeypatch.setattr(
        rs.PredictionResolverScheduler, "_run_refresh_cycle", _quick_cycle
    )
    rs.stop_prediction_resolver_scheduler()
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._active = True
    sched._first_tick_pending = True
    sched._revive_use_full_budget = False
    out = sched._run_refresh_cycle_with_timeout()
    assert out.get("ok") is True
    owner_gen = sched._cycle_generation
    assert owner_gen >= 1
    sched._cycle_lock.acquire()
    sched._lock_owner_gen = owner_gen
    rs._scheduler = sched
    seen: dict[str, object] = {}
    real_abandon = sched._abandon_inflight_cycle

    def _trace(**kwargs):
        seen.update(kwargs)
        return real_abandon(**kwargs)

    monkeypatch.setattr(sched, "_abandon_inflight_cycle", _trace)
    try:
        revived = rs.revive_prediction_resolver_scheduler(force=True)
        assert revived.get("stale_lock_recycled") is True
        assert seen.get("submitted_gen") == owner_gen
    finally:
        rs.stop_prediction_resolver_scheduler()


def test_revive_stale_lock_recycle_passes_lock_owner_gen_to_abandon(
    tmp_path, monkeypatch
):
    """CR-06: stale wedge abandon must target published _lock_owner_gen, not default gen."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "_resolver_tick_age_seconds", lambda: 10000.0)
    monkeypatch.setattr(rs, "_resolver_cycle_lock_stale", lambda *a, **k: True)
    rs.stop_prediction_resolver_scheduler()
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    owner = sched._cycle_generation
    sched._cycle_lock.acquire()
    sched._lock_owner_gen = owner
    rs._scheduler = sched
    seen: dict[str, object] = {}
    real_abandon = sched._abandon_inflight_cycle

    def _trace(**kwargs):
        seen.update(kwargs)
        return real_abandon(**kwargs)

    monkeypatch.setattr(sched, "_abandon_inflight_cycle", _trace)
    try:
        out = rs.revive_prediction_resolver_scheduler(force=True)
        assert out.get("stale_lock_recycled") is True
        assert seen.get("submitted_gen") == owner
    finally:
        rs.stop_prediction_resolver_scheduler()


def test_no_unowned_cycle_lock_while_held_during_cycle_start(tmp_path, monkeypatch):
    """Regression: acquire + owner publish share _release_guard (no revive/abandon wedge)."""
    probe = _OrphanProbe()
    _patch_orphan_env(tmp_path, monkeypatch, probe)
    monkeypatch.setattr(rs, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 30)
    monkeypatch.setattr(rs, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 30)
    rs.stop_prediction_resolver_scheduler()
    sched = _fresh_scheduler()
    stop = threading.Event()
    violations: list[str] = []
    watcher_errors: list[BaseException] = []

    def _watch():
        try:
            while not stop.is_set():
                with sched._release_guard:
                    if sched._cycle_lock.locked() and sched._lock_owner_gen is None:
                        violations.append(
                            "unowned locked cycle observed under release_guard"
                        )
                time.sleep(0.0005)
        except BaseException as exc:
            watcher_errors.append(exc)

    watcher = threading.Thread(target=_watch, daemon=True)
    watcher.start()
    try:
        _caller, fut = _start_blocked_cycle(sched, probe)
        assert sched._lock_owner_gen is not None
        assert sched._cycle_lock.locked()
        probe.release.set()
        futures_wait([fut], timeout=5)
    finally:
        stop.set()
        probe.release.set()
        watcher.join(timeout=2)
        rs.stop_prediction_resolver_scheduler()
    assert not watcher_errors, watcher_errors
    assert not violations, violations


def test_revive_at_owner_barrier_abandons_without_overlap(tmp_path, monkeypatch):
    """Pause after atomic owner publish; stale revive abandons once, no second persist overlap."""
    probe = _OrphanProbe()
    _patch_orphan_env(tmp_path, monkeypatch, probe)
    monkeypatch.setattr(rs, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 30)
    monkeypatch.setattr(rs, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 30)
    monkeypatch.setattr(rs, "_resolver_tick_age_seconds", lambda: 10000.0)
    rs.stop_prediction_resolver_scheduler()
    sched = _fresh_scheduler()
    barrier_released = threading.Event()
    at_barrier = threading.Event()
    first_gen = {}

    def _barrier(_sched, gen):
        first_gen["gen"] = gen
        at_barrier.set()
        assert _sched._lock_owner_gen == gen
        assert _sched._cycle_lock.locked()
        barrier_released.wait(timeout=3)

    rs._cycle_lock_post_register_barrier = _barrier
    persist_gens = []
    real_persist = sched._persist_cycle_summary

    def _track_persist(result, *args, **kwargs):
        if isinstance(result, dict) and result.get("ok") is True:
            persist_gens.append(result.get("cycle_generation"))
        return real_persist(result, *args, **kwargs)

    monkeypatch.setattr(sched, "_persist_cycle_summary", _track_persist)
    try:
        caller = threading.Thread(target=sched._run_refresh_cycle_with_timeout, daemon=True)
        caller.start()
        assert at_barrier.wait(timeout=5)
        out = rs.revive_prediction_resolver_scheduler(force=True)
        assert out.get("stale_lock_recycled") is True
        barrier_released.set()
        probe.release.set()
        caller.join(timeout=5)
        assert not caller.is_alive()
        assert len(persist_gens) <= 1
        if persist_gens:
            assert persist_gens[0] != first_gen.get("gen")
    finally:
        rs._cycle_lock_post_register_barrier = None
        barrier_released.set()
        probe.release.set()
        rs.stop_prediction_resolver_scheduler()


def test_revive_full_budget_retained_after_failed_lock_acquire(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.learning.loop_health.SOUL_MAP_PATH", str(soul))
    rs.stop_prediction_resolver_scheduler()
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._revive_use_full_budget = True
    sched._first_tick_pending = True
    sched._cycle_lock.acquire()
    try:
        out = sched._run_refresh_cycle_with_timeout()
        assert out.get("skipped") == "cycle_in_flight"
        assert sched._revive_use_full_budget is True
    finally:
        sched._cycle_lock.release()
        rs.stop_prediction_resolver_scheduler()


def test_revive_not_blocked_during_skip_summary_persist(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    seeded_last_cycle = {
        "run_at": "2099-01-01T00:00:00Z",
        "ok": True,
        "cycle_generation": 3,
    }
    soul.write_text(
        json.dumps(
            {
                "prediction_resolver_scheduler": {
                    "last_cycle": dict(seeded_last_cycle),
                    "lifecycle": "running",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.learning.loop_health.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "_resolver_tick_age_seconds", lambda: 10000.0)

    rs.stop_prediction_resolver_scheduler()
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    monkeypatch.setattr(
        sched,
        "_run_refresh_cycle",
        lambda: (_ for _ in ()).throw(
            AssertionError("stale scheduler must not enter real cycle")
        ),
    )
    sched._active = True
    gen = sched._cycle_generation
    sched._cycle_lock.acquire()
    sched._lock_owner_gen = gen
    rs._scheduler = sched
    persist_gate = threading.Event()
    persist_release = threading.Event()
    real_persist = sched._persist_cycle_summary

    def slow_skip_persist(result, *args, **kwargs):
        if isinstance(result, dict) and result.get("skipped") == "cycle_in_flight":
            persist_gate.set()
            persist_release.wait(timeout=2)
        return real_persist(result, *args, **kwargs)

    monkeypatch.setattr(sched, "_persist_cycle_summary", slow_skip_persist)
    try:
        skip_thread = threading.Thread(target=sched._run_refresh_cycle_with_timeout, daemon=True)
        skip_thread.start()
        assert persist_gate.wait(timeout=2)
        revived = {}

        def _revive():
            revived["out"] = rs.revive_prediction_resolver_scheduler(force=True)

        rt = threading.Thread(target=_revive, daemon=True)
        rt.start()
        rt.join(timeout=2)
        assert not rt.is_alive()
        assert revived["out"].get("revived") is True
        assert rs._scheduler is not sched
        persist_release.set()
        skip_thread.join(timeout=2)
        data = json.loads(soul.read_text(encoding="utf-8"))
        terminal = data["prediction_resolver_scheduler"]["last_cycle"]
        assert terminal["run_at"] == seeded_last_cycle["run_at"]
        assert terminal["cycle_generation"] == seeded_last_cycle["cycle_generation"]
    finally:
        persist_release.set()
        rs.stop_prediction_resolver_scheduler()


def test_stale_skip_summary_cannot_clobber_new_scheduler_last_cycle(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps(
            {
                "prediction_resolver_scheduler": {
                    "last_cycle": {
                        "run_at": "2099-01-02T00:00:00Z",
                        "ok": True,
                        "cycle_generation": 2,
                    },
                    "lifecycle": "running",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.learning.loop_health.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "_resolver_tick_age_seconds", lambda: 10000.0)
    rs.stop_prediction_resolver_scheduler()
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._active = True
    gen = sched._cycle_generation
    sched._cycle_lock.acquire()
    sched._lock_owner_gen = gen
    rs._scheduler = sched
    persist_gate = threading.Event()
    persist_release = threading.Event()
    real_persist = sched._persist_cycle_summary

    def slow_skip_persist(result, *args, **kwargs):
        if isinstance(result, dict) and result.get("skipped") == "cycle_in_flight":
            persist_gate.set()
            persist_release.wait(timeout=2)
        return real_persist(result, *args, **kwargs)

    monkeypatch.setattr(sched, "_persist_cycle_summary", slow_skip_persist)
    try:
        skip_thread = threading.Thread(target=sched._run_refresh_cycle_with_timeout, daemon=True)
        skip_thread.start()
        assert persist_gate.wait(timeout=2)
        rs.revive_prediction_resolver_scheduler(force=True)
        persist_release.set()
        skip_thread.join(timeout=2)
        data = json.loads(soul.read_text(encoding="utf-8"))
        assert data["prediction_resolver_scheduler"]["last_cycle"]["run_at"] == "2099-01-02T00:00:00Z"
    finally:
        persist_release.set()
        rs.stop_prediction_resolver_scheduler()


def test_revive_full_budget_selects_full_timeout_on_acquire(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.learning.loop_health.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 3)
    monkeypatch.setattr(rs, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 1)
    started = threading.Event()
    release = threading.Event()

    def _blocked(self):
        started.set()
        release.wait(timeout=5)
        return {
            "ok": True,
            "run_at": rs._now_iso(),
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
        }

    monkeypatch.setattr(rs.PredictionResolverScheduler, "_run_refresh_cycle", _blocked)
    rs.stop_prediction_resolver_scheduler()
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._first_tick_pending = True
    sched._revive_use_full_budget = True
    try:
        t0 = time.monotonic()
        out = sched._run_refresh_cycle_with_timeout()
        elapsed = time.monotonic() - t0
        assert started.wait(timeout=1)
        assert elapsed >= 2.0
        assert "cycle_timeout_3" in str(out.get("error", ""))
    finally:
        release.set()
        rs.stop_prediction_resolver_scheduler()


def test_revive_budget_barrier_before_selection_uses_full_timeout(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.learning.loop_health.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 2)
    monkeypatch.setattr(rs, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 1)
    barrier_hit = threading.Event()
    continue_barrier = threading.Event()
    worker_release = threading.Event()

    def _barrier(sched):
        sched._revive_use_full_budget = True
        barrier_hit.set()
        continue_barrier.wait(timeout=2)

    rs._revive_budget_acquire_barrier = _barrier
    started = threading.Event()

    def _blocked(self):
        started.set()
        worker_release.wait(timeout=5)
        return {
            "ok": True,
            "run_at": rs._now_iso(),
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
        }

    monkeypatch.setattr(rs.PredictionResolverScheduler, "_run_refresh_cycle", _blocked)
    rs.stop_prediction_resolver_scheduler()
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._first_tick_pending = True
    result: dict = {}

    def _run():
        result["out"] = sched._run_refresh_cycle_with_timeout()

    try:
        runner = threading.Thread(target=_run, daemon=True)
        runner.start()
        assert barrier_hit.wait(timeout=2)
        continue_barrier.set()
        runner.join(timeout=8)
        assert started.wait(timeout=1)
        assert "cycle_timeout_2" in str(result.get("out", {}).get("error", ""))
    finally:
        continue_barrier.set()
        worker_release.set()
        rs._revive_budget_acquire_barrier = None
        rs.stop_prediction_resolver_scheduler()


def test_old_generation_timeout_cannot_clobber_newer_last_cycle(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps(
            {
                "prediction_resolver_scheduler": {
                    "last_cycle": {
                        "run_at": "2099-06-01T00:00:00Z",
                        "ok": True,
                        "cycle_generation": 10,
                    },
                    "lifecycle": "running",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._persist_owner_gen = None
    sched._lifecycle = "running"
    stale = {
        "run_at": "2026-01-01T00:00:00Z",
        "ok": False,
        "resolved_now": 0,
        "expired_now": 0,
        "pending": 0,
        "error": "cycle_timeout_90s",
        "cycle_generation": 3,
    }
    sched._persist_cycle_summary(stale, owner_gen=3, force=True)
    data = json.loads(soul.read_text(encoding="utf-8"))
    assert data["prediction_resolver_scheduler"]["last_cycle"]["cycle_generation"] == 10

