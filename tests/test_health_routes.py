"""HTTP tests for health liveness probes (slice 14b + #1072 hardening)."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from internal.health import routes as health_routes
from server import app


def test_api_health_returns_ok_json():
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ops_live_timeout_returns_honest_degraded(monkeypatch):
    monkeypatch.setattr(health_routes, "OPS_LIVE_HANDLER_TIMEOUT", 0.05)

    def _slow():
        time.sleep(0.2)
        return {"status": "ok", "live": True}

    with patch.object(health_routes, "build_ops_live_report_sync", side_effect=_slow):
        body = TestClient(app).get("/api/ops/live").json()
    assert body["status"] == "degraded"
    assert body["live"] is False
    assert body.get("error") == "timeout"
    assert body["worker_mode"] == "unknown"


def test_health_non_blocking_during_slow_ops_live(monkeypatch):
    """Sync liveness work must not wedge the event loop (uptime curl -m 20 → HTTP 000)."""
    monkeypatch.setattr(health_routes, "OPS_LIVE_HANDLER_TIMEOUT", 2.0)
    release = threading.Event()

    def _slow():
        release.wait(timeout=2.0)
        return {"status": "ok", "live": True, "volume": {}, "worker_peer": {}}

    with patch.object(health_routes, "build_ops_live_report_sync", side_effect=_slow):
        with TestClient(app) as client:
            result = {}

            def _call_live():
                result["resp"] = client.get("/api/ops/live")

            t = threading.Thread(target=_call_live, daemon=True)
            t.start()
            time.sleep(0.2)

            t0 = time.monotonic()
            health = client.get("/health")
            api_health = client.get("/api/health")
            elapsed = time.monotonic() - t0

            release.set()
            t.join(timeout=3.0)

    assert health.status_code == 200
    assert health.text.strip() == "OK"
    assert api_health.status_code == 200
    assert api_health.json() == {"status": "ok"}
    assert elapsed < 1.0
    assert result["resp"].status_code == 200
