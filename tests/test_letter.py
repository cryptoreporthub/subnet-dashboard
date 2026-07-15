"""§17.F4 — weekly letter API."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from internal.letter.generator import build_weekly_letter
from server import app


def test_weekly_letter_honest_empty(tmp_path, monkeypatch):
    path = tmp_path / "daily_picks.json"
    path.write_text("[]")

    monkeypatch.setattr(
        "internal.portfolio.engine.build_portfolio_status",
        lambda: {
            "summary": {
                "total_closed": 0,
                "win_pct": 0.0,
                "win_count": 0,
                "total_pnl_pct": 0.0,
                "excess_vs_hold_tao_pct": 0.0,
            }
        },
    )
    monkeypatch.setattr(
        "internal.council.scenario_memory.get_memory_snapshot",
        lambda: {"scenarios": []},
    )

    letter = build_weekly_letter(daily_picks_path=str(path))
    assert letter["status"] == "ok"
    assert letter["empty"] is True
    assert "No top pick data yet" in letter["markdown"]
    assert "No gradeable resolved picks yet" in letter["markdown"]
    assert "No scenarios recorded yet" in letter["markdown"]


def test_weekly_letter_with_data(tmp_path, monkeypatch):
    path = tmp_path / "daily_picks.json"
    path.write_text(
        json.dumps(
            [
                {
                    "date": "2026-07-15",
                    "action": "long",
                    "pick": {"subnet": {"netuid": 19, "name": "Nineteen"}, "action": "long"},
                    "reason": "Strong momentum",
                }
            ]
        )
    )
    monkeypatch.setattr(
        "internal.portfolio.engine.build_portfolio_status",
        lambda: {
            "summary": {
                "total_closed": 10,
                "win_pct": 0.6,
                "win_count": 6,
                "total_pnl_pct": 12.5,
                "excess_vs_hold_tao_pct": 12.5,
            }
        },
    )
    monkeypatch.setattr(
        "internal.council.scenario_memory.get_memory_snapshot",
        lambda: {
            "scenarios": [
                {"id": "a", "name": "alpha", "regime": "bull", "outcome": "hit"},
                {"id": "b", "name": "beta", "regime": "bear", "outcome": "miss"},
                {"id": "c", "name": "gamma", "regime": "volatile", "outcome": "hit"},
                {"id": "d", "name": "delta", "regime": "neutral", "outcome": "hit"},
            ]
        },
    )

    letter = build_weekly_letter(daily_picks_path=str(path))
    assert letter["empty"] is False
    assert letter["top_pick"]["summary"] == "SN19 Nineteen"
    assert letter["win_rate"]["win_pct"] == 0.6
    assert len(letter["scenarios"]) == 3
    assert "SN19 Nineteen" in letter["markdown"]
    assert "60.0%" in letter["markdown"]
    assert "delta" in letter["markdown"]  # last 3 of 4


def test_api_letter_weekly_200():
    client = TestClient(app)
    resp = client.get("/api/letter/weekly")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "markdown" in body
