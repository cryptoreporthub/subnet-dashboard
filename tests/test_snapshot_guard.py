"""Regression tests for learning snapshot single-flight prewarming."""

from __future__ import annotations

import threading


def _reset_guard(monkeypatch, guard, original):
    monkeypatch.setattr(guard, "_ORIG", original)
    monkeypatch.setattr(guard, "_LOCK", threading.Lock())
    monkeypatch.setattr(guard, "_BUILDING", threading.Event())
    monkeypatch.setattr(guard, "_LAST_GOOD", {"at": 0.0, "data": None, "cold": True})


def test_snapshot_guard_cold_build_is_cached(monkeypatch):
    import internal.snapshot_guard as guard

    calls = {"count": 0}

    def _build():
        calls["count"] += 1
        return {"engine_stats": {"total_records": calls["count"]}}

    _reset_guard(monkeypatch, guard, _build)

    first = guard._patched()
    second = guard._patched()

    assert first == second
    assert calls["count"] == 1


def test_snapshot_guard_prewarm_runs_without_waiting_for_interval(monkeypatch):
    import internal.snapshot_guard as guard

    calls = {"count": 0}

    def _build():
        calls["count"] += 1
        return {"engine_stats": {}}

    _reset_guard(monkeypatch, guard, _build)
    monkeypatch.setenv("LEARNING_SNAPSHOT_PREWARM_SECONDS", "60")

    guard._prewarm_once()

    assert calls["count"] == 1
    assert guard._LAST_GOOD["cold"] is False


def test_snapshot_guard_returns_stale_while_building(monkeypatch):
    import internal.snapshot_guard as guard

    stale = {"engine_stats": {"total_records": 3}}
    _reset_guard(monkeypatch, guard, lambda: {"engine_stats": {"total_records": 4}})
    guard._LAST_GOOD.update(at=0.0, data=stale, cold=False)
    guard._BUILDING.set()

    assert guard._patched() is stale
