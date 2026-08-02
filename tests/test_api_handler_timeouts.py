"""Regression: bare thread-offload handlers must return degraded JSON on timeout."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from internal.judges import council_routes
from server import app


def test_api_judges_timeout_returns_degraded(monkeypatch):
    monkeypatch.setattr(council_routes, "JUDGES_HANDLER_TIMEOUT", 0.05)

    def _slow():
        time.sleep(2)
        return {"success": True, "judges": [{"netuid": 1}], "count": 1}

    monkeypatch.setattr(council_routes, "_api_judges_sync", _slow)
    resp = TestClient(app).get("/api/judges")
    assert resp.status_code == 200
    assert resp.json() == {
        "success": False,
        "error": "timeout",
        "judges": [],
        "count": 0,
    }
