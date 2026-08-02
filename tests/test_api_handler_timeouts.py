"""Regression: bare thread-offload handlers must return degraded JSON on timeout."""

from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from internal.judges import council_routes
from internal.letter import routes as letter_routes
from server import app


def test_api_judges_timeout_returns_degraded(monkeypatch):
    monkeypatch.setattr(council_routes, "JUDGES_HANDLER_TIMEOUT", 0.05)

    def _slow():
        time.sleep(2)
        return {"success": True, "judges": [{"netuid": 1}], "count": 1}

    monkeypatch.setattr(council_routes, "_api_judges_sync_inner", _slow)
    resp = TestClient(app).get("/api/judges")
    assert resp.status_code == 200
    assert resp.json() == {
        "success": False,
        "error": "timeout",
        "judges": [],
        "count": 0,
    }


def test_api_judges_timeout_returns_stale_cache(monkeypatch):
    monkeypatch.setattr(council_routes, "JUDGES_HANDLER_TIMEOUT", 0.05)
    stale = {"success": True, "judges": [{"netuid": 7}], "count": 1, "source": "registry"}
    council_routes._JUDGES_CACHE["payload"] = stale
    council_routes._JUDGES_CACHE["at"] = time.time()

    def _slow():
        time.sleep(2)
        return {"success": True, "judges": [{"netuid": 1}], "count": 1}

    monkeypatch.setattr(council_routes, "_api_judges_sync_inner", _slow)
    resp = TestClient(app).get("/api/judges")
    assert resp.status_code == 200
    assert resp.json() == stale


def test_learning_health_ok_while_judges_blocked(monkeypatch):
    monkeypatch.setattr(council_routes, "JUDGES_HANDLER_TIMEOUT", 30.0)
    gate = threading.Event()

    def _block():
        gate.wait(timeout=5)
        return {"success": True, "judges": [], "count": 0}

    monkeypatch.setattr(council_routes, "_api_judges_sync_inner", _block)

    client = TestClient(app)
    judges_thread = threading.Thread(target=lambda: client.get("/api/judges"))
    judges_thread.start()
    time.sleep(0.05)

    health = client.get("/api/learning/health")
    gate.set()
    judges_thread.join(timeout=5)

    assert health.status_code == 200
    body = health.json()
    assert "status" in body
    assert body.get("error") != "timeout"


def test_api_letter_weekly_timeout_returns_degraded(monkeypatch):
    monkeypatch.setattr(letter_routes, "LETTER_HANDLER_TIMEOUT", 0.05)

    def _slow():
        time.sleep(2)
        return {"status": "ok", "empty": False, "week_of": "2026-01-01", "markdown": "x"}

    monkeypatch.setattr(letter_routes, "build_weekly_letter", _slow)
    resp = TestClient(app).get("/api/letter/weekly")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "timeout"
    assert body["empty"] is True
    assert body["markdown"] == ""
