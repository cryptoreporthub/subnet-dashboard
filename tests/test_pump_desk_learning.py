"""Pump desk self-learning — grading, trust line, calibration."""

from __future__ import annotations

import json

import pytest

from internal.council import resolver, weights
from internal.council.grading import grade_prediction, pump_lead_hit
from internal.council.resolver import resolve_prediction
from internal.learning import predictions_store
from internal.learning.pump_alert import build_pump_alerts
from internal.learning.pump_calibration import (
    load_calibration,
    maybe_adapt_after_resolve,
)
from internal.learning.pump_lead_stats import build_pump_desk_trust


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    pred = str(tmp_path / "predictions.json")
    cal = str(tmp_path / "pump_calibration.json")
    soul = str(tmp_path / "soul_map.json")
    soul_obj = tmp_path / "soul_map.json"
    soul_obj.write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.0,
                        "hype": 1.0,
                        "dark_horse": 1.0,
                        "technical": 1.0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", pred)
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", pred)
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", soul)
    monkeypatch.setattr("internal.learning.pump_calibration.CALIBRATION_PATH", cal)
    monkeypatch.setenv("PUMP_CALIBRATION_PATH", cal)


def _pump_row(**kwargs):
    base = {
        "id": "p1",
        "netuid": 28,
        "pick_source": "pump_lead",
        "direction": "up",
        "predicted_pct": 2.0,
        "pump_claim": "ACCUMULATING",
        "pump_badge": "BUILDING",
        "pump_phase": "ACCUMULATING",
        "correct": True,
        "outcome": "hit",
        "actual_pct": 3.0,
    }
    base.update(kwargs)
    return base


def test_pump_lead_hit_requires_two_pct_for_early():
    pred = {"pick_source": "pump_lead", "predicted_pct": 2.0, "pump_claim": "ACCUMULATING"}
    assert pump_lead_hit(pred, 1.0) is False
    assert pump_lead_hit(pred, 2.0) is True
    assert pump_lead_hit(pred, 2.5) is True
    correct, outcome = grade_prediction(pred, 1.0)
    assert correct is False and outcome == "miss"


def test_just_started_grades_still_positive():
    pred = {
        "pick_source": "pump_lead",
        "predicted_pct": 2.0,
        "pump_claim": "JUST_STARTED",
        "pump_badge": "JUST STARTED",
    }
    assert pump_lead_hit(pred, 0.5) is True
    assert pump_lead_hit(pred, -0.1) is False


def test_resolver_uses_pump_claim_not_direction_only():
    pred = {
        "id": "pump1",
        "netuid": 1,
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 100.0,
        "horizon_hours": 1,
        "horizon_type": "pump_lead",
        "pick_source": "pump_lead",
        "pump_claim": "ACCUMULATING",
        "resolve_at": "2099-01-01T00:00:00Z",
        "status": "pending",
    }
    out = resolve_prediction(dict(pred), current_price=101.0)
    assert out.get("correct") is False
    assert out.get("outcome") == "miss"

    hit = resolve_prediction(
        {**pred, "id": "pump2", "status": "pending"},
        current_price=103.0,
    )
    assert hit.get("correct") is True
    assert hit.get("outcome") == "hit"


def test_council_stats_exclude_pump_lead():
    data = {
        "predictions": [],
        "resolved": [
            {
                "pick_source": "council",
                "correct": True,
                "outcome": "hit",
                "actual_pct": 1.0,
            },
            _pump_row(correct=False, outcome="miss", actual_pct=1.0),
        ],
    }
    stats = resolver._compute_stats(data)
    assert stats["correct"] == 1
    assert stats["wrong"] == 0


def test_trust_line_builds_from_early_grades():
    rows = [
        _pump_row(
            id=f"e{i}",
            correct=(i % 2 == 0),
            actual_pct=2.5 if i % 2 == 0 else 0.5,
        )
        for i in range(6)
    ]
    trust = build_pump_desk_trust({"resolved": rows, "predictions": []})
    assert trust["ready"] is True
    assert trust["early"]["n"] == 6
    assert "hit 2%+" in trust["line"]
    assert "n=6" in trust["line"]


def test_build_pump_alerts_includes_trust(monkeypatch):
    monkeypatch.setattr(
        "internal.pump.state.load_state",
        lambda: {"subnets": {}, "meta": {}},
    )
    out = build_pump_alerts([])
    assert "trust" in out
    assert out["trust"].get("line")


def test_adapt_skips_until_n30():
    rows = [_pump_row(id=f"e{i}", correct=False, actual_pct=0.5) for i in range(10)]
    predictions_store.save_predictions({"predictions": [], "resolved": rows, "stats": {}})
    assert maybe_adapt_after_resolve(min_sample=30) is None


def test_adapt_tightens_when_hit_rate_weak():
    rows = [_pump_row(id=f"e{i}", correct=False, actual_pct=0.5) for i in range(30)]
    predictions_store.save_predictions({"predictions": [], "resolved": rows, "stats": {}})
    before = load_calibration()
    out = maybe_adapt_after_resolve(min_sample=30)
    assert out is not None
    assert out["lead_buy_ratio_min"] > before["lead_buy_ratio_min"]
    assert out["adapted_from_n"] == 30
