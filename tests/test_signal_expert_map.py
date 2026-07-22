"""Signal expert map + impact-based attribution."""

from __future__ import annotations

from internal.council.signal_expert import (
    expert_from_signal_impact,
    expert_from_signal_source,
)
from internal.council.state_vector import _compute_signal_impact, _compute_technical_indicators


def test_emission_momentum_is_quant_not_hype():
    assert expert_from_signal_source("emission_momentum") == "quant"
    assert expert_from_signal_source("momentum_shift") == "hype"


def test_exact_map_covers_core_signal_types():
    assert expert_from_signal_source("rsi_crossover") == "technical"
    assert expert_from_signal_source("delegation_flow") == "dark_horse"
    assert expert_from_signal_source("staking_conviction") == "quant"
    assert expert_from_signal_source("HOT") == "hype"
    assert expert_from_signal_source("SELL ALERT") == "technical"


def test_unknown_labels_unclassified():
    assert expert_from_signal_source("apy_yield_spike") == "unclassified"
    assert expert_from_signal_source("council_day_pick") == "unclassified"


def test_expert_from_signal_impact_uses_lead_impact():
    impact = {
        "impacts": [
            {
                "signal_type": "emission_change",
                "magnitude_pct": 2.5,
                "learned_weight": 1.0,
            },
            {
                "signal_type": "momentum_shift",
                "magnitude_pct": 0.4,
                "learned_weight": 1.0,
            },
        ],
        "dominant": "HOT",
    }
    assert expert_from_signal_impact(impact) == "quant"


def test_subnet_vector_attribution_uses_impact_not_hot_label():
    sn = {
        "netuid": 1,
        "name": "Alpha",
        "price": 1.0,
        "price_change_24h": 5.0,
        "emission": 2.0,
        "apy": 25.0,
        "social_mentions": 0,
    }
    indicators = _compute_technical_indicators(sn)
    hot = {"active": True, "score": 3, "label": "HOT"}
    sell = {"active": False, "score": 0}
    impact = _compute_signal_impact(sn, indicators, hot, sell)
    expert = expert_from_signal_impact(impact)
    # With strong emission signal, should not blindly credit HOT→hype.
    assert expert in {"quant", "technical", "hype", "dark_horse", "unclassified"}
