"""Resolver scheduler in-place revive (loop stall guard strike 1)."""

from __future__ import annotations

import json
import threading
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


def test_revive_recycles_when_stale_lock_held(tmp_path, monkeypatch):
    """P4a: held _cycle_lock + proven-stale tick must recycle, not dead-end.

    Prod wedge: the timeout path failed to release _cycle_lock, revive returned
    tick_in_progress forever, and the stall guard (one-shot revive) could never
    recover. A healthy cycle can never hold the lock past stall_after_s, so
    recycling on a provably stale tick is safe.
    """
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
    monkeypatch.setattr(rs, "_resolver_tick_age_seconds", lambda: 7200.0)

    rs.stop_prediction_resolver_scheduler()
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._active = True
    rs._scheduler = sched
    sched._cycle_lock.acquire()  # simulate the wedged holder

    try:
        out = rs.revive_prediction_resolver_scheduler(force=True)
        assert out["recycled"] is True
        assert out.get("reason") == "stale_lock_recycled"
        assert out["tick"].get("ok") is True
        new = rs.get_prediction_resolver_scheduler()
        assert new is not None and new is not sched
        assert new._cycle_lock.acquire(blocking=False)
        new._cycle_lock.release()
    finally:
        sched._cycle_lock.release()
        rs.stop_prediction_resolver_scheduler()


def test_revive_honest_tick_in_progress_when_lock_held_not_stale(tmp_path, monkeypatch):
    """Held lock without staleness proof stays tick_in_progress (live tick)."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.learning.loop_health.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "_resolver_tick_age_seconds", lambda: None)

    rs.stop_prediction_resolver_scheduler()
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._active = True
    rs._scheduler = sched
    sched._cycle_lock.acquire()

    try:
        out = rs.revive_prediction_resolver_scheduler(force=True)
        assert out["revived"] is False
        assert out.get("reason") == "tick_in_progress"
        assert out["recycled"] is False
        assert rs.get_prediction_resolver_scheduler() is sched
    finally:
        sched._cycle_lock.release()
        rs.stop_prediction_resolver_scheduler()

