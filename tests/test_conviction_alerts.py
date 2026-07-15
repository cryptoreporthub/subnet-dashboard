"""O1 conviction-threshold alert tests."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from internal.conviction_alerts.evaluate import (
    get_conviction_config,
    run_conviction_evaluation,
)
from internal.signals.alerts import AlertEngine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    alerts = tmp_path / "alerts.json"
    subs = tmp_path / "subs.json"
    alerts.write_text(json.dumps({"alerts": []}), encoding="utf-8")
    subs.write_text(json.dumps({"webhooks": []}), encoding="utf-8")
    monkeypatch.setenv("ALERTS_PATH", str(alerts))
    monkeypatch.setenv("ALERT_SUBSCRIPTIONS_PATH", str(subs))
    monkeypatch.delenv("CONVICTION_ALERTS_ENABLED", raising=False)
    return AlertEngine(alerts_path=str(alerts), subscriptions_path=str(subs))


def test_conviction_disabled_by_default(engine):
    result = run_conviction_evaluation(engine)
    assert result["enabled"] is False
    assert result["reason"] == "disabled"
    assert result["created_count"] == 0


def test_conviction_creates_alert_when_enabled(engine, tmp_path, monkeypatch):
    monkeypatch.setenv("CONVICTION_ALERTS_ENABLED", "on")
    monkeypatch.setenv("CONVICTION_ALERT_MIN", "70")
    picks = tmp_path / "daily_picks.json"
    picks.write_text(
        json.dumps(
            [
                {
                    "date": "2099-01-01",
                    "pick": {
                        "final_confidence": 0.82,
                        "action": "long",
                        "subnet": {"netuid": 8, "name": "Proprietary"},
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DAILY_PICKS_PATH", str(picks))
    from internal.conviction_alerts import evaluate as ev

    monkeypatch.setattr(ev, "_today_str", lambda: "2099-01-01")

    result = run_conviction_evaluation(engine)
    assert result["created_count"] == 1
    assert result["created"][0]["alert_type"] == "conviction_threshold"


def test_conviction_dedupes_second_run(engine, tmp_path, monkeypatch):
    monkeypatch.setenv("CONVICTION_ALERTS_ENABLED", "on")
    picks = tmp_path / "daily_picks.json"
    picks.write_text(
        json.dumps(
            [
                {
                    "date": "2099-01-01",
                    "pick": {
                        "final_confidence": 80,
                        "subnet": {"netuid": 3, "name": "Test"},
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DAILY_PICKS_PATH", str(picks))
    from internal.conviction_alerts import evaluate as ev

    monkeypatch.setattr(ev, "_today_str", lambda: "2099-01-01")
    first = run_conviction_evaluation(engine)
    second = run_conviction_evaluation(engine)
    assert first["created_count"] == 1
    assert second["created_count"] == 0


def test_status_endpoint():
    from server import app

    client = TestClient(app)
    resp = client.get("/api/conviction-alerts/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "enabled" in body
    assert "tiers" in body


def test_notify_endpoint_disabled():
    from server import app

    client = TestClient(app)
    resp = client.post("/api/conviction-alerts/notify")
    assert resp.status_code == 200
    assert resp.json()["reason"] == "disabled"


def test_config_shape():
    cfg = get_conviction_config()
    assert cfg["tiers"]["cyan"] == 75
    assert cfg["enabled"] is False
