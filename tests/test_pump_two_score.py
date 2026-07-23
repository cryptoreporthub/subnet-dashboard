"""Upgrade 5 — two-score (accum predictive vs confirm)."""

from __future__ import annotations

from internal.pump.engine import classify_signals, compute_composite_score
from internal.pump.two_score import (
    CONFIRM_PUMP_MIN,
    apply_confirm_pump_gate,
    compute_accum_score,
    compute_confirm_score,
    score_layer_for_phase,
)


def test_accum_emphasizes_flow_over_price():
    flow_heavy = {
        "volume_intensity": 0.9,
        "buy_ratio": 0.75,
        "chatter_intensity": 0.2,
        "price_change_24h": 0.0,
        "momentum_1h": 0.0,
    }
    price_heavy = {
        "volume_intensity": 0.1,
        "buy_ratio": 0.5,
        "chatter_intensity": 0.0,
        "price_change_24h": 0.12,
        "momentum_1h": 0.05,
    }
    assert compute_accum_score(flow_heavy) > compute_accum_score(price_heavy)
    assert compute_confirm_score(price_heavy) > compute_confirm_score(flow_heavy)


def test_confirm_gate_blocks_pumping_without_price(monkeypatch):
    # Force composite path to want PUMPING; weak confirm must hold at ACCUMULATING.
    monkeypatch.setattr(
        "internal.pump.engine.raw_phase_from_score",
        lambda score, was_pumping=False: "PUMPING",
    )
    signals = {
        "netuid": 9,
        "name": "FlowOnly",
        "volume_intensity": 0.95,
        "buy_ratio": 0.8,
        "chatter_intensity": 0.5,
        "scenario_tag": "risk_on",
        "price_change_24h": 0.0,
        "momentum_1h": 0.0,
    }
    confirm = compute_confirm_score(signals)
    assert confirm < CONFIRM_PUMP_MIN
    result = classify_signals(signals)
    assert result["suggested_phase"] == "ACCUMULATING"
    assert result["score_layer"] == "predictive"
    assert "accum_score" in result and "confirm_score" in result


def test_confirm_gate_allows_pumping_with_price():
    signals = {
        "netuid": 9,
        "name": "Hot",
        "volume_intensity": 0.95,
        "buy_ratio": 0.8,
        "chatter_intensity": 0.5,
        "scenario_tag": "risk_on",
        "price_change_24h": 0.12,
        "momentum_1h": 0.05,
    }
    result = classify_signals(signals)
    assert result["confirm_score"] >= CONFIRM_PUMP_MIN
    assert result["suggested_phase"] == "PUMPING"
    assert result["score_layer"] == "confirm"


def test_apply_confirm_pump_gate_helper():
    assert apply_confirm_pump_gate("PUMPING", 0.1) == "ACCUMULATING"
    assert apply_confirm_pump_gate("PUMPING", 0.5) == "PUMPING"
    assert apply_confirm_pump_gate("STIRRING", 0.0) == "STIRRING"


def test_score_layer_for_phase():
    assert score_layer_for_phase("STIRRING") == "predictive"
    assert score_layer_for_phase("PUMPING") == "confirm"
    assert score_layer_for_phase("DORMANT") == "none"
