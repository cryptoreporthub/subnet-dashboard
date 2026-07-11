"""Live contract tests for /api/pump-tracker/* — never 500, subnets always a list."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_engine_ladder(tmp_path, monkeypatch):
    state_path = str(tmp_path / "pump_ladder.json")
    state_path_obj = tmp_path / "pump_ladder.json"
    state_path_obj.write_text(
        json.dumps(
            {
                "version": "1.0",
                "subnets": {
                    "1": {
                        "netuid": 1,
                        "name": "Alpha",
                        "phase": "ACCUMULATING",
                        "since": "2026-07-11T00:00:00Z",
                        "composite_score": 0.55,
                        "transitions": [
                            {
                                "time": "2026-07-11T00:05:00Z",
                                "from_phase": "STIRRING",
                                "to_phase": "ACCUMULATING",
                                "composite_score": 0.55,
                            }
                        ],
                    },
                    "2": {
                        "netuid": 2,
                        "name": "Beta",
                        "phase": "PUMPING",
                        "since": "2026-07-11T00:00:00Z",
                        "composite_score": 0.72,
                        "transitions": [],
                    },
                },
                "meta": {"last_scan_at": "2026-07-11T00:10:00Z"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PUMP_LADDER_STATE_PATH", state_path)
    from internal.pump import constants

    monkeypatch.setattr(constants, "STATE_PATH", state_path)
    yield state_path


def _assert_ok_dict(body: dict) -> None:
    assert isinstance(body, dict)
    assert "status" in body
    assert body["status"] in {"success", "unavailable", "error"}


def test_ladder_live_uses_engine_not_legacy(client, fake_engine_ladder):
    resp = client.get("/api/pump-tracker/ladder")
    assert resp.status_code == 200
    body = resp.json()
    _assert_ok_dict(body)
    assert body["status"] == "success"
    assert body["source"] == "internal.pump.state"
    assert isinstance(body["subnets"], list)
    assert len(body["subnets"]) == 2
    assert all(isinstance(row, dict) for row in body["subnets"])
    assert body["subnets"][0]["current_phase"] in {
        "ACCUMULATING",
        "PUMPING",
        "DORMANT",
        "STIRRING",
        "COOLING",
    }


def test_top_movers_live_from_engine_transitions(client, fake_engine_ladder):
    resp = client.get("/api/pump-tracker/top-movers?limit=5")
    assert resp.status_code == 200
    body = resp.json()
    _assert_ok_dict(body)
    assert body["status"] == "success"
    assert isinstance(body.get("movers"), list)
    assert body["count"] >= 1
    assert body["movers"][0]["from_phase"] == "STIRRING"


def test_summary_live_never_500(client, fake_engine_ladder):
    resp = client.get("/api/pump-tracker/summary")
    assert resp.status_code == 200
    body = resp.json()
    _assert_ok_dict(body)
    assert body["status"] == "success"
    summary = body["summary"]
    assert isinstance(summary, dict)
    assert summary.get("sentences")
    assert "ACCUMULATING" in summary["text"] or "PUMPING" in summary["text"]


def test_phase_filter_live(client, fake_engine_ladder):
    resp = client.get("/api/pump-tracker/phase/PUMPING")
    assert resp.status_code == 200
    body = resp.json()
    _assert_ok_dict(body)
    assert body["status"] == "success"
    assert body["phase"] == "PUMPING"
    assert isinstance(body["subnets"], list)
    assert all(row.get("current_phase") == "PUMPING" for row in body["subnets"])


def test_phase_accumulating_live(client, fake_engine_ladder):
    """Agent A five-phase vocab: GET /phase/ACCUMULATING must succeed."""
    resp = client.get("/api/pump-tracker/phase/ACCUMULATING")
    assert resp.status_code == 200
    body = resp.json()
    _assert_ok_dict(body)
    assert body["status"] == "success"
    assert body["phase"] == "ACCUMULATING"
    assert isinstance(body["subnets"], list)
    assert len(body["subnets"]) == 1
    assert body["subnets"][0]["current_phase"] == "ACCUMULATING"


def test_legacy_path_survives_dict_subnets(client):
    """Simulate legacy analytics returning subnets as dict — must not int.get crash."""
    fake_analytics = {
        "status": "success",
        "data": {
            "subnets": {
                7: {
                    "netuid": 7,
                    "name": "SN7",
                    "current_phase": "INACTIVE",
                    "pump_score": 0.1,
                    "final_score": 0.2,
                    "pump_proneness": 10,
                }
            },
            "meta": {"tracked_subnets": 1, "total_cycles": 0},
        },
    }

    with patch("internal.pump_tracker.adapter._engine_ladder_snapshot", return_value=None):
        with patch("internal.pump_tracker.core.get_pump_tracker") as mock_tracker:
            tracker = mock_tracker.return_value
            tracker.get_all_analytics.return_value = fake_analytics
            tracker.get_current_phases.return_value = {7: {"phase": "INACTIVE", "duration_min": 0}}
            resp = client.get("/api/pump-tracker/ladder")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert isinstance(body["subnets"], list)
