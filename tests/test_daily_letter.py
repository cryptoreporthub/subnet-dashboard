"""§17.F4b — daily recap letter API."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from internal.letter.generator import build_daily_letter
from server import app


def test_daily_letter_honest_empty(tmp_path, monkeypatch):
    picks_path = tmp_path / "daily_picks.json"
    picks_path.write_text("[]")
    preds = tmp_path / "predictions.json"
    preds.write_text(json.dumps({"predictions": [], "resolved": []}), encoding="utf-8")

    import internal.learning.predictions_store as ps

    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr(
        "internal.council.scenario_memory.get_memory_snapshot",
        lambda: {"scenarios": []},
    )
    alerts_path = tmp_path / "alerts.json"
    alerts_path.write_text(json.dumps({"alerts": []}))
    monkeypatch.setattr("internal.letter.generator.ALERTS_PATH", str(alerts_path))

    letter = build_daily_letter(date="2026-07-14", daily_picks_path=str(picks_path))
    assert letter["status"] == "ok"
    assert letter["empty"] is True
    assert letter["date"] == "2026-07-14"
    assert "No council picks recorded" in letter["markdown"]
    assert "No gradeable resolutions" in letter["markdown"]


def test_daily_letter_with_data(tmp_path, monkeypatch):
    picks_path = tmp_path / "daily_picks.json"
    picks_path.write_text(
        json.dumps(
            [
                {
                    "date": "2026-07-14",
                    "action": "long",
                    "pick": {"subnet": {"netuid": 19, "name": "Nineteen"}, "action": "long"},
                    "reason": "Momentum",
                }
            ]
        )
    )
    preds = tmp_path / "predictions.json"
    preds.write_text(
        json.dumps(
            {
                "predictions": [],
                "resolved": [
                    {
                        "id": "r1",
                        "netuid": 7,
                        "name": "Sub7",
                        "direction": "up",
                        "predicted_pct": 5.0,
                        "actual_pct": 6.0,
                        "resolved_at": "2026-07-14T12:00:00Z",
                        "correct": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    import internal.learning.predictions_store as ps

    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr(
        "internal.council.scenario_memory.get_memory_snapshot",
        lambda: {
            "scenarios": [
                {
                    "id": "s1",
                    "name": "alpha",
                    "regime": "bull",
                    "outcome": "hit",
                    "created_at": "2026-07-14T08:00:00Z",
                }
            ]
        },
    )
    alerts_path = tmp_path / "alerts.json"
    alerts_path.write_text(json.dumps({"alerts": []}))
    monkeypatch.setattr("internal.letter.generator.ALERTS_PATH", str(alerts_path))

    letter = build_daily_letter(date="2026-07-14", daily_picks_path=str(picks_path))
    assert letter["empty"] is False
    assert letter["stats"]["pick_count"] == 1
    assert letter["stats"]["resolved_count"] == 1
    assert letter["stats"]["correct"] == 1
    assert letter["picks"][0]["summary"] == "SN19 Nineteen"
    assert "SN19 Nineteen" in letter["markdown"]
    assert "alpha" in letter["markdown"]


def test_api_letter_daily_200():
    client = TestClient(app)
    resp = client.get("/api/letter/daily")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "markdown" in body
    assert body.get("default_window") == "yesterday_utc"
