"""Cut A+B (#1058): hydrate handlers off REQUEST_EXECUTOR + load-shed reclass."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from internal.health import routes as health_routes
from internal.learning import routes as learning_routes
from internal.portfolio import routes as portfolio_routes
from server import app

_HYDRATE_OFFLOAD_ROUTES = (
    ("/api/mindmap/trail", "internal.learning.mindmap_aggregator.collect_trail_events"),
    ("/api/story-strip", "internal.analytics.story_strip.build_story_strip"),
    ("/api/portfolio/status", "internal.portfolio.engine.build_portfolio_status"),
    ("/api/subnet-integrations", "internal.integrations.status.build_integrations_status"),
    ("/api/ops/evidence", "internal.ops.evidence.build_evidence_report"),
)


def test_offloaded_hydrate_routes_do_not_block_health():
    """Blocking sync builders must run on REQUEST_EXECUTOR so /health stays fast."""
    for path, target in _HYDRATE_OFFLOAD_ROUTES:
        release = threading.Event()

        def _slow(*_a, **_k):
            release.wait(timeout=2.0)
            if "trail" in target:
                return []
            if "story_strip" in target:
                return {
                    "data_available": False,
                    "reason": "no_resolved_outcomes",
                    "items": [],
                    "stats": {"correct": 0, "wrong": 0},
                }
            if "portfolio" in target:
                return {"status": "ok", "empty": True, "benchmark": "hold_tao", "summary": {}}
            if "integrations" in target:
                return {
                    "integrations": [],
                    "candidates": [],
                    "connected_count": 0,
                    "integration_total": 0,
                    "ready_for_launch": False,
                    "cached": False,
                }
            return {"status": "ok", "alerts": []}

        with patch(target, side_effect=_slow):
            with TestClient(app) as client:
                result = {}

                def _call():
                    result["resp"] = client.get(path)

                t = threading.Thread(target=_call, daemon=True)
                t.start()
                time.sleep(0.2)

                t0 = time.monotonic()
                health = client.get("/health")
                elapsed = time.monotonic() - t0

                release.set()
                t.join(timeout=3.0)

        assert health.status_code == 200, path
        assert elapsed < 1.0, f"{path} blocked /health for {elapsed:.2f}s"
        assert result["resp"].status_code == 200, path


def test_mindmap_trail_timeout_is_honest(monkeypatch):
    monkeypatch.setattr(learning_routes, "MINDMAP_TRAIL_HANDLER_TIMEOUT", 0.05)

    def _slow():
        time.sleep(0.2)
        return []

    with patch("internal.learning.mindmap_aggregator.collect_trail_events", side_effect=_slow):
        body = TestClient(app).get("/api/mindmap/trail").json()
    assert body["status"] == "timeout"
    assert body["trail"] == []
    assert body.get("error") == "timeout"


def test_story_strip_timeout_is_honest(monkeypatch):
    monkeypatch.setattr(learning_routes, "STORY_STRIP_HANDLER_TIMEOUT", 0.05)

    def _slow(**_k):
        time.sleep(0.2)
        return {"data_available": True, "items": [{"id": "x"}], "stats": {"correct": 1, "wrong": 0}}

    with patch("internal.analytics.story_strip.build_story_strip", side_effect=_slow):
        body = TestClient(app).get("/api/story-strip").json()
    assert body["data_available"] is False
    assert body["reason"] == "timeout"
    assert body["items"] == []


def test_portfolio_status_timeout_is_honest(monkeypatch):
    monkeypatch.setattr(portfolio_routes, "PORTFOLIO_HANDLER_TIMEOUT", 0.05)

    def _slow():
        time.sleep(0.2)
        return {"status": "ok", "empty": False, "benchmark": "hold_tao", "summary": {}}

    with patch("internal.portfolio.engine.build_portfolio_status", side_effect=_slow):
        body = TestClient(app).get("/api/portfolio/status").json()
    assert body["status"] == "timeout"
    assert body.get("error") == "timeout"
    assert body["empty"] is True


def test_subnet_integrations_timeout_is_honest(monkeypatch):
    monkeypatch.setattr(health_routes, "SUBNET_INTEGRATIONS_HANDLER_TIMEOUT", 0.05)

    def _slow(**_k):
        time.sleep(0.2)
        return {"integrations": [{"slug": "x"}], "connected_count": 1, "ready_for_launch": True}

    with patch("internal.integrations.status.build_integrations_status", side_effect=_slow):
        body = TestClient(app).get("/api/subnet-integrations").json()
    assert body.get("error") == "timeout"
    assert body["integrations"] == []
    assert body["ready_for_launch"] is False


def test_ops_evidence_timeout_is_honest(monkeypatch):
    monkeypatch.setattr(health_routes, "OPS_EVIDENCE_HANDLER_TIMEOUT", 0.05)

    def _slow():
        time.sleep(0.2)
        return {"status": "ok", "alerts": ["fake-success"]}

    with patch("internal.ops.evidence.build_evidence_report", side_effect=_slow):
        body = TestClient(app).get("/api/ops/evidence").json()
    assert body["status"] == "timeout"
    assert body.get("error") == "timeout"
    assert body["alerts"] == []
