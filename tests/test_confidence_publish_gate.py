"""Healthy picks must be able to clear the 45% publish gate (do not lower the gate)."""

from __future__ import annotations

import json

import pytest

from internal.council import state_vector as sv
from internal.council.red_team import audit_daily_pick


@pytest.fixture(autouse=True)
def isolate_predictions(tmp_path, monkeypatch):
    pred_path = str(tmp_path / "predictions.json")
    monkeypatch.setattr("internal.council.resolver.PREDICTIONS_PATH", pred_path)
    with open(pred_path, "w") as f:
        json.dump({"predictions": [], "resolved": []}, f)
    yield


def test_cold_start_healthy_survives_mild_red_team_haircut():
    """Prior must not hard-cap at 0.5 — that forced HOLD on any audit cut."""
    sn = {
        "netuid": 64,
        "name": "Chutes",
        "price": 1.2,
        "volume": 12_000,
        "confidence": None,  # filled below
    }
    indicators = {"history_length": 30}
    experts = {"quant": 0.62, "hype": 0.60, "dark_horse": 0.58, "technical": 0.61}
    raw = sv._compute_confidence(sn, indicators, experts)
    assert raw > 0.45
    sn["confidence"] = raw
    audit = audit_daily_pick(sn, [sn])
    assert audit["adjusted_confidence"] >= 0.45


def test_buy_sell_volume_counts_as_complete():
    """TMC/chain rows often expose buy+sell instead of unified volume."""
    sn = {
        "netuid": 3,
        "name": "Templar",
        "price": 0.4,
        "buy_volume_24h": 8000,
        "sell_volume_24h": 7000,
    }
    indicators = {"history_length": 30}
    experts = {"quant": 0.6, "hype": 0.6, "dark_horse": 0.6, "technical": 0.6}
    conf = sv._compute_confidence(sn, indicators, experts)
    assert conf == pytest.approx(sv._COLD_START_PRIOR, rel=1e-3)


def test_short_ohlcv_still_penalized_but_can_clear_gate():
    sn = {"netuid": 11, "name": "A", "price": 1.0, "volume": 5000}
    indicators = {"history_length": 8}
    experts = {"quant": 0.6, "hype": 0.6, "dark_horse": 0.6, "technical": 0.6}
    conf = sv._compute_confidence(sn, indicators, experts)
    # 0.62 * 0.85 * 1.0
    assert conf == pytest.approx(sv._COLD_START_PRIOR * 0.85, rel=1e-3)
    assert conf > 0.45
