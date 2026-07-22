"""§17.F3 — council paper portfolio from resolved picks."""

from __future__ import annotations

from fastapi.testclient import TestClient

from internal.portfolio.engine import build_portfolio_status
from server import app


def test_portfolio_status_empty():
    status = build_portfolio_status({"predictions": [], "resolved": []})
    assert status["empty"] is True
    assert status["summary"]["total_closed"] == 0
    assert status["summary"]["total_pnl_pct"] == 0.0
    assert status["summary"]["hold_tao_pnl_pct"] == 0.0
    assert status["closed_positions"] == []
    assert status["open_positions"] == []


def test_portfolio_follows_resolved_no_fake_fills():
    data = {
        "predictions": [
            {
                "id": "open-1",
                "netuid": 1,
                "name": "Pending",
                "direction": "up",
                "predicted_pct": 2.0,
                "created_at": "2026-07-01T00:00:00Z",
            }
        ],
        "resolved": [
            {
                "id": "r1",
                "netuid": 40,
                "name": "Ralph",
                "direction": "up",
                "predicted_pct": 5.0,
                "actual_pct": 10.0,
                "resolved_at": "2026-07-02T00:00:00Z",
            },
            {
                "id": "r2",
                "netuid": 3,
                "name": "Templar",
                "direction": "down",
                "predicted_pct": -3.0,
                "actual_pct": -4.0,
                "resolved_at": "2026-07-03T00:00:00Z",
            },
            {
                "id": "skip",
                "netuid": 9,
                "direction": "up",
                "predicted_pct": 1.0,
                "actual_pct": 2.0,
                "outcome": "duplicate",
            },
            {
                "id": "no-actual",
                "netuid": 10,
                "direction": "up",
                "predicted_pct": 1.0,
            },
        ],
    }
    status = build_portfolio_status(data)
    assert status["empty"] is False
    assert status["summary"]["total_closed"] == 2
    assert status["summary"]["win_count"] == 2
    # up+10 long → +10; down+-4 short → +4
    assert status["summary"]["total_pnl_pct"] == 14.0
    assert status["summary"]["avg_pnl_pct"] == 7.0
    assert status["summary"]["excess_vs_hold_tao_pct"] == 14.0
    assert status["summary"]["hold_tao_pnl_pct"] == 0.0
    assert len(status["open_positions"]) == 1
    assert status["open_positions"][0]["id"] == "open-1"
    assert all(p["id"] != "skip" for p in status["closed_positions"])


def test_api_portfolio_status_200():
    client = TestClient(app)
    resp = client.get("/api/portfolio/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "summary" in body
    assert "closed_positions" in body
    assert body["benchmark"] == "hold_tao"
