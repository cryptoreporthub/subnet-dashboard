"""Acc-2 — horizon align (24h) + publish gate tighten (50%)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from internal.council.publish_gate import publish_gate_fraction, publish_gate_percent
from internal.council.state_vector import attach_council_prediction, clamp_prediction_horizon
from internal.learning.pick_horizon import day_horizon_hours
from internal.learning.prediction_loop import record_pick_prediction


def test_day_horizon_defaults_24(monkeypatch):
    monkeypatch.delenv("ACC2_DAY_HORIZON_HOURS", raising=False)
    monkeypatch.delenv("DAY_PICK_HORIZON_HOURS", raising=False)
    assert day_horizon_hours() == 24


def test_day_horizon_rollback_env(monkeypatch):
    monkeypatch.setenv("ACC2_DAY_HORIZON_HOURS", "4")
    assert day_horizon_hours() == 4


def test_publish_gate_defaults_50(monkeypatch):
    monkeypatch.delenv("DAILY_PICK_PUBLISH_GATE", raising=False)
    assert publish_gate_fraction() == pytest.approx(0.50)
    assert publish_gate_percent() == 50


def test_clamp_day_horizon_allows_24(monkeypatch):
    monkeypatch.delenv("ACC2_DAY_HORIZON_HOURS", raising=False)
    assert clamp_prediction_horizon(24, horizon_type="day") == 24
    assert clamp_prediction_horizon(24, horizon_type="hour") == 4


def test_record_day_prediction_uses_24h(monkeypatch, tmp_path):
    monkeypatch.delenv("ACC2_DAY_HORIZON_HOURS", raising=False)
    pred_path = tmp_path / "predictions.json"
    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr("internal.learning.prediction_loop.has_pending_duplicate", lambda *a, **k: False)

    subnet = {"netuid": 15, "name": "Test", "price": 1.0, "volume": 500000}
    pick = {
        "subnet": subnet,
        "score": 8.0,
        "confidence": 0.55,
        "final_confidence": 0.55,
        "expert_contributions": {"quant": 0.6},
    }
    row = record_pick_prediction(pick, subnet, horizon_type="day")
    assert row is not None
    assert row.get("horizon_hours") == 24
    assert row.get("horizon_type") == "day"


def test_attach_council_prediction_day_horizon(monkeypatch):
    monkeypatch.delenv("ACC2_DAY_HORIZON_HOURS", raising=False)
    pred = attach_council_prediction(
        {"netuid": 1, "name": "A", "price": 1.0},
        {"confidence": 0.5, "signal_impact": {"net_direction": "up"}},
        0.55,
        horizon_type="day",
    )
    assert pred["horizon_hours"] == 24


def test_council_prediction_timestamps_are_parseable_utc():
    pred = attach_council_prediction(
        {"netuid": 1, "name": "A", "price": 1.0},
        {"confidence": 0.5, "signal_impact": {"net_direction": "up"}},
        0.55,
        horizon_type="hour",
        horizon_hours=1,
    )
    created = datetime.fromisoformat(pred["created_at"].replace("Z", "+00:00"))
    resolve_at = datetime.fromisoformat(pred["resolve_at"].replace("Z", "+00:00"))
    assert created.tzinfo == timezone.utc
    assert resolve_at > created
    assert "+00:00Z" not in pred["created_at"]
    assert "+00:00Z" not in pred["resolve_at"]
