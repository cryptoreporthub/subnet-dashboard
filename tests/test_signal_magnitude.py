"""§17.S2 — signal-derived predicted_pct (no confidence proxy)."""

from __future__ import annotations

import json

import pytest

import internal.council.scenario_memory as scenario_memory
import internal.learning.predictions_store as predictions_store
from internal.learning.prediction_loop import (
    _predicted_pct_from_pick,
    record_pick_prediction,
)


@pytest.fixture(autouse=True)
def _iso_paths(monkeypatch, tmp_path):
    scen = tmp_path / "scenario_memory.json"
    pred = tmp_path / "predictions.json"
    monkeypatch.setattr(scenario_memory, "SCENARIO_MEMORY_PATH", str(scen))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred))
    scen.write_text(json.dumps({"scenarios": [], "regimes": {}, "meta": {}}))
    pred.write_text(
        json.dumps(
            {
                "predictions": [],
                "resolved": [],
                "stats": {"total": 0, "correct": 0, "wrong": 0, "pending": 0},
            }
        )
    )


def test_predicted_pct_uses_signal_impact_not_confidence():
    pick = {
        "action": "long",
        "confidence": 0.99,  # would have been ~5% under old proxy
        "final_confidence": 0.99,
        "signal_impact": {"net_predicted_pct": 2.25, "net_direction": "bullish"},
    }
    subnet = {"netuid": 7, "name": "Test", "price": 1.0, "price_change_24h": 0.1}
    pct, source = _predicted_pct_from_pick(pick, subnet)
    assert source == "signal_impact"
    assert pct == 2.25
    # Prove confidence proxy unused: old formula max(0.5, 0.99*5)=4.95
    assert abs(pct - 4.95) > 1.0


def test_predicted_pct_market_momentum_fallback():
    pick = {"action": "long", "confidence": 0.99, "final_confidence": 0.99}
    subnet = {
        "netuid": 7,
        "name": "Test",
        "price": 1.0,
        "price_change_24h": 4.0,
        "market_cap": 20_000,
    }
    pct, source = _predicted_pct_from_pick(pick, subnet)
    assert source == "market_momentum"
    assert pct != pytest.approx(4.95)  # not confidence*5


def test_record_pick_tags_magnitude_source():
    pick = {
        "subnet": {"netuid": 11, "name": "Alpha", "price": 2.0},
        "score": 70,
        "confidence": 0.8,
        "expert_contributions": {"quant": 0.6, "hype": 0.5, "dark_horse": 0.4, "technical": 0.5},
        "signal_impact": {"net_predicted_pct": -1.5, "net_direction": "bearish"},
    }
    subnet = {
        "netuid": 11,
        "name": "Alpha",
        "price": 2.0,
        "volume": 1000,
        "price_change_24h": -1.0,
        "emission": 1.0,
    }
    stored = record_pick_prediction(pick, subnet, horizon_type="hour")
    assert stored is not None
    assert stored.get("magnitude_source") == "signal_impact"
    assert stored.get("predicted_pct") == -1.5
    assert stored.get("magnitude_source") != "confidence_proxy"
