"""Tests for internal/analytics/backtest.py (Phase N4)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from internal.analytics.backtest import evaluate_judges, run_backtest
from server import app


_FIXTURE = {
    "predictions": [],
    "resolved": [
        {
            "id": "hit-up",
            "netuid": 1,
            "name": "Alpha",
            "direction": "up",
            "predicted_pct": 5.0,
            "actual_pct": 3.2,
            "status": "resolved",
            "signal_source": "HOT",
            "reference_price": 1.0,
        },
        {
            "id": "miss-down",
            "netuid": 2,
            "name": "Beta",
            "direction": "down",
            "predicted_pct": -4.0,
            "actual_pct": 2.5,
            "status": "resolved",
            "signal_source": "SELL ALERT",
            "reference_price": 1.0,
        },
        {
            "id": "skip-dup",
            "netuid": 3,
            "direction": "up",
            "predicted_pct": 1.0,
            "actual_pct": 1.0,
            "status": "resolved",
            "outcome": "duplicate",
        },
    ],
    "stats": {},
}


@pytest.fixture
def client():
    return TestClient(app)


def test_run_backtest_counts_gradeable_rows():
    result = run_backtest(data=_FIXTURE)
    assert result["status"] == "success"
    assert result["sample_size"] == 2
    assert result["council"]["wins"] == 1
    assert result["council"]["losses"] == 1
    assert result["council"]["win_rate"] == 0.5
    for judge in ("oracle", "echo", "pulse"):
        assert judge in result["judges"]
        assert result["judges"][judge]["win_rate"] is not None
        assert "filtered" in result["judges"][judge]
        assert len(result["judges"][judge]["calibration"]) == 10


def test_run_backtest_empty():
    result = run_backtest(data={"predictions": [], "resolved": [], "stats": {}})
    assert result["status"] == "empty"
    assert result["sample_size"] == 0


def test_evaluate_judges_scores_bounded():
    row = _FIXTURE["resolved"][0]
    scores = evaluate_judges(row)
    for judge in ("oracle", "echo", "pulse"):
        assert 0 <= scores[judge]["score"] <= 1
        assert 0 <= scores[judge]["confidence"] <= 1


def test_api_backtest_route(client):
    resp = client.get("/api/backtest?limit=50")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") in ("success", "empty", "error")
    assert "judges" in body or body.get("status") == "error"


def test_api_report_route(client):
    resp = client.get("/api/report/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("netuid") == 1
    assert "markdown" in body
