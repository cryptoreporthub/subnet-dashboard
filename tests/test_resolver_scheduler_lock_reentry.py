"""Bounded repro for CodeRabbit scheduler-lock reentry hypothesis (PR #1571)."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

import internal.council.resolver_scheduler as rs
import internal.learning.loop_health as loop_health


def test_scheduler_lock_is_non_reentrant_reference():
    """Baseline: second acquire on same Lock blocks (not reentrant)."""
    lock = threading.Lock()
    lock.acquire()
    progressed = threading.Event()

    def _blocked():
        lock.acquire()
        progressed.set()

    t = threading.Thread(target=_blocked, daemon=True)
    t.start()
    t.join(timeout=0.3)
    assert not progressed.is_set()
    lock.release()
    t.join(timeout=0.3)


def test_cold_tick_age_rebuild_touches_scheduler_state(monkeypatch):
    """Cold cache miss: tick age → liveness view → get_prediction_resolver_scheduler_state."""
    seen = threading.Event()

    def _state():
        seen.set()
        return {"lifecycle": "stopped", "refresh_minutes": 15}

    monkeypatch.setattr(rs, "get_prediction_resolver_scheduler_state", _state)
    loop_health._RESOLVER_LIVENESS_CACHE.update({"at": 0.0, "payload": None, "seq": -1})
    loop_health._RESOLVER_LIVENESS_BUILDING = False
    rs._resolver_tick_age_seconds()
    assert seen.is_set()


def test_revive_tick_in_progress_with_cold_cache_returns_bounded(tmp_path, monkeypatch):
    """Revive must not call tick age rebuild while holding _scheduler_lock."""
    import json

    import internal.council.weights as weights

    soul = tmp_path / "soul_map.json"
    tick = datetime.now(timezone.utc) - timedelta(seconds=45)
    soul.write_text(
        json.dumps(
            {
                "prediction_resolver_scheduler": {
                    "last_cycle": {"run_at": tick.isoformat().replace("+00:00", "Z"), "ok": True}
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.learning.loop_health.SOUL_MAP_PATH", str(soul))
    loop_health._RESOLVER_LIVENESS_CACHE.update({"at": 0.0, "payload": None, "seq": -1})
    loop_health._RESOLVER_LIVENESS_BUILDING = False

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

    monkeypatch.setattr(rs, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 120)
    monkeypatch.setattr(rs, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 120)
    monkeypatch.setattr(rs.PredictionResolverScheduler, "_run_refresh_cycle", _blocked)
    rs.stop_prediction_resolver_scheduler()
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._active = True
    sched._first_tick_pending = False
    rs._scheduler = sched
    try:
        caller = threading.Thread(target=sched._run_refresh_cycle_with_timeout, daemon=True)
        caller.start()
        assert started.wait(timeout=1)
        out_holder: dict = {}

        def _revive():
            out_holder["out"] = rs.revive_prediction_resolver_scheduler(force=True)

        rev = threading.Thread(target=_revive, daemon=True)
        rev.start()
        rev.join(timeout=3)
        assert not rev.is_alive(), "revive hung (scheduler_lock reentry?)"
        assert out_holder.get("out", {}).get("reason") == "tick_in_progress"
    finally:
        release.set()
        rs.stop_prediction_resolver_scheduler()
