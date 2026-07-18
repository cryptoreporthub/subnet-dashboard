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
            "subnet_snapshot": {
                "price": 1.0,
                "apy": 0.2,
                "emission": 1.0,
                "price_change_24h": 2.0,
                "price_change_7d": 5.0,
            },
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
            "subnet_snapshot": {
                "price": 1.0,
                "apy": 0.2,
                "emission": 1.0,
                "price_change_24h": -1.0,
                "price_change_7d": -2.0,
            },
        },
        {
            "id": "council-miss",
            "netuid": 3,
            "name": "Gamma",
            "direction": "up",
            "predicted_pct": 4.0,
            "actual_pct": -2.0,
            "status": "resolved",
            "signal_source": "council_hour_pick",
            "expert": "quant",
            "reference_price": 1.0,
        },
        {
            "id": "skip-dup",
            "netuid": 4,
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
    assert result["sample_size"] == 3
    assert result["council"]["wins"] == 1
    assert result["council"]["losses"] == 2
    assert result["council"]["win_rate"] == round(1 / 3, 4)
    for judge in ("oracle", "echo", "pulse"):
        assert judge in result["judges"]
        assert result["judges"][judge]["win_rate"] is not None
        assert result["judges"][judge]["endorsed_n"] is not None
        assert "filtered" in result["judges"][judge]
        assert len(result["judges"][judge]["calibration"]) == 10


def test_judge_filtered_rates_can_differ_from_council():
    result = run_backtest(data=_FIXTURE)
    council_rate = result["council"]["win_rate"]
    oracle_filtered = result["judges"]["oracle"]["filtered"]
    assert oracle_filtered["n"] >= 1
    assert oracle_filtered["win_rate"] is not None
    rates = {
        judge: result["judges"][judge]["filtered"]["win_rate"]
        for judge in ("oracle", "echo", "pulse")
        if result["judges"][judge]["filtered"]["n"] > 0
    }
    assert len(set(rates.values())) >= 1
    assert council_rate is not None


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
    if body.get("status") == "success":
        assert "methodology" in body
        assert body["methodology"].get("sources")
        assert body["council"].get("coverage_pct") == 100.0


def test_api_report_route(client):
    resp = client.get("/api/report/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("netuid") == 1
    assert "markdown" in body
