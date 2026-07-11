"""Phase D — pump-tracker read API + mindmap summary (Agent B)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_pump_tracker_ladder_endpoint(client):
    resp = client.get("/api/pump-tracker/ladder")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"success", "unavailable", "error"}
    assert "subnets" in body
    if body["status"] == "success":
        assert isinstance(body["subnets"], list)


def test_pump_tracker_phase_filter(client):
    resp = client.get("/api/pump-tracker/phase/DORMANT")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("phase") == "DORMANT"
    assert "subnets" in body
    if body.get("status") == "success":
        assert all(row.get("current_phase") == "DORMANT" for row in body["subnets"])


def test_pump_tracker_phase_accumulating(client):
    resp = client.get("/api/pump-tracker/phase/ACCUMULATING")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("phase") == "ACCUMULATING"
    assert body["status"] in {"success", "unavailable", "error"}
    assert "subnets" in body
    if body.get("status") == "error":
        assert "Unknown phase" not in body.get("error", "")


def test_pump_tracker_top_movers(client):
    resp = client.get("/api/pump-tracker/top-movers?limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"success", "unavailable", "error"}
    assert "movers" in body


def test_pump_tracker_summary_endpoint(client):
    resp = client.get("/api/pump-tracker/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    summary = body["summary"]
    assert summary["sentences"]
    assert len(summary["text"]) > 20


def test_mindmap_state_includes_pump_tracker_summary(client):
    state = client.get("/api/mindmap/state").json()
    assert state["status"] == "success"
    assert "pump_tracker" in state.get("summaries", {})


def test_guarded_import_when_engine_missing():
    with patch("internal.pump_tracker.adapter.get_ladder_snapshot", side_effect=Exception("boom")):
        from internal.learning.panel_summaries import summarize_pump_tracker_guarded

        assert summarize_pump_tracker_guarded() is None


def test_unavailable_response_when_no_engine(client):
    from internal.pump_tracker.adapter import PumpEngineUnavailable

    with patch(
        "internal.pump_tracker.routes.get_ladder_snapshot",
        side_effect=PumpEngineUnavailable("offline"),
    ):
        resp = client.get("/api/pump-tracker/ladder")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unavailable"
    assert "pump engine unavailable" in body["error"]
