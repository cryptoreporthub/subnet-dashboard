"""Regression tests for learning-health stale-while-compute behavior."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from internal.learning import routes as learning_routes
from server import app


def _valid_health():
    return {
        "status": "ok",
        "checked_at": "2026-08-13T00:00:00Z",
        "pending": 1,
        "last_resolver_tick": "2026-08-13T00:00:00Z",
        "resolver": {"running": True},
        "worker_peer": {"alive": True},
        "watchdog": {},
        "daily_pick": {},
        "ledger": {},
        "snapshot_age_seconds": 0,
        "score_snapshot": {},
    }


def _reset_health_state():
    learning_routes._LEARNING_HEALTH_CACHE["payload"] = None
    learning_routes._LEARNING_HEALTH_CACHE["at"] = 0.0
    learning_routes._LEARNING_HEALTH_BUILDING = False


def test_learning_health_timeout_serves_last_good_payload(monkeypatch):
    import internal.learning.loop_health as loop_health

    _reset_health_state()
    stale = _valid_health()
    learning_routes._LEARNING_HEALTH_CACHE.update(payload=stale, at=time.time() - 1)
    monkeypatch.setattr(learning_routes, "_LEARNING_HEALTH_CACHE_TTL", 0.01)
    monkeypatch.setattr(learning_routes, "_LEARNING_HEALTH_STALE_TTL", 60.0)
    monkeypatch.setattr(learning_routes, "LEARNING_HEALTH_TIMEOUT", 0.01)

    def _slow():
        time.sleep(0.1)
        return _valid_health()

    monkeypatch.setattr(loop_health, "build_learning_loop_health", _slow)
    response = TestClient(app).get("/api/learning/health")

    assert response.status_code == 200
    assert response.json()["meta"]["source"] == "stale_timeout"
    assert response.json()["meta"]["stale"] is True
    time.sleep(0.12)


def test_learning_health_cold_timeout_is_bounded_and_single_flight(monkeypatch):
    import internal.learning.loop_health as loop_health

    _reset_health_state()
    monkeypatch.setattr(learning_routes, "LEARNING_HEALTH_TIMEOUT", 0.01)
    calls = {"count": 0}

    def _slow():
        calls["count"] += 1
        time.sleep(0.1)
        return _valid_health()

    monkeypatch.setattr(loop_health, "build_learning_loop_health", _slow)
    client = TestClient(app)

    first = client.get("/api/learning/health")
    started = time.time()
    second = client.get("/api/learning/health")
    elapsed = time.time() - started

    assert first.status_code == 200
    assert first.json()["meta"]["source"] == "timeout"
    assert second.status_code == 200
    assert second.json()["meta"]["source"] == "refreshing"
    assert elapsed < 0.5
    time.sleep(0.12)
    assert calls["count"] == 1
