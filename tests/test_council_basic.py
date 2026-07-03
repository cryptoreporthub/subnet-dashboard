"""
Basic unit tests for the Council state-vector engine.

These tests exercise the scoring, RedTeam audit, and daily pick selection
without requiring live API keys or external network calls.
"""

import pytest

from internal.council.state_vector import score_subnet_for_hour, score_subnet_for_day
from internal.council.red_team import audit_daily_pick
from internal.council.daily_pick import select_daily_pick


def _sample_subnet(netuid: int = 1, **overrides) -> dict:
    return {
        "netuid": netuid,
        "name": f"SN{netuid}",
        "symbol": f"SN{netuid}",
        "emission": 2.0,
        "apy": 40.0,
        "volume": 600_000,
        "market_cap": 15_000_000,
        "price": 10.0,
        "price_change_24h": 8.0,
        "price_change_7d": 15.0,
        "price_change_30d": 30.0,
        "status": "active",
        **overrides,
    }


def test_score_subnet_for_hour_shape():
    sn = _sample_subnet()
    result = score_subnet_for_hour(sn, {"tao_change_24h": 2.0})

    assert isinstance(result, dict)
    assert 0 <= result["total_score"] <= 100
    assert 0 <= result["confidence"] <= 1
    assert set(result["expert_contributions"].keys()) == {
        "quant", "hype", "contrarian", "technical",
        "signal_contributions", "active_signals", "technical_score",
    }
    assert set(result["scenario_tags"].keys()) == {"regime", "rsi", "volume", "price_direction"}
    assert result["horizon"] == "hour"
    assert result["horizon_type"] == "hour"


def test_score_subnet_for_day_shape():
    sn = _sample_subnet()
    result = score_subnet_for_day(sn, {"tao_change_24h": -4.0})

    assert isinstance(result, dict)
    assert 0 <= result["total_score"] <= 100
    assert 0 <= result["confidence"] <= 1
    assert set(result["expert_contributions"].keys()) == {
        "quant", "hype", "contrarian", "technical",
        "signal_contributions", "active_signals", "technical_score",
    }
    assert result["scenario_tags"]["regime"] == "bearish"
    assert result["horizon"] == "day"
    assert result["horizon_type"] == "day"


def test_hour_vs_day_weight_difference():
    sn = _sample_subnet()
    hour = score_subnet_for_hour(sn)
    day = score_subnet_for_day(sn)
    # Hour lens overweights hype/technical; day lens overweights quant/contrarian.
    assert hour["weights_used"]["hype"] > day["weights_used"]["hype"]
    assert day["weights_used"]["quant"] > hour["weights_used"]["quant"]


def test_audit_daily_pick_approves_healthy_candidate():
    candidate = _sample_subnet()
    audit = audit_daily_pick(candidate, [candidate])
    assert audit["approved"] is True
    assert 0 <= audit["adjusted_confidence"] <= 1


def test_audit_daily_pick_flags_low_volume():
    candidate = _sample_subnet(volume=50_000)
    audit = audit_daily_pick(candidate, [candidate])
    assert any("Low liquidity" in c for c in audit["concerns"])


def test_audit_daily_pick_flags_extreme_volatility():
    candidate = _sample_subnet(price_change_24h=25.0)
    audit = audit_daily_pick(candidate, [candidate])
    assert any("Extreme 24h volatility" in c for c in audit["concerns"])


def test_audit_daily_pick_rejects_missing_fields():
    candidate = _sample_subnet()
    del candidate["price"]
    audit = audit_daily_pick(candidate, [candidate])
    assert audit["approved"] is False
    assert any("Missing critical field: price" in c for c in audit["concerns"])


def test_select_daily_pick_returns_payload():
    subnets = [
        _sample_subnet(netuid=1, emission=2.0, volume=600_000),
        _sample_subnet(netuid=2, emission=0.5, volume=50_000, price_change_24h=-5.0),
    ]
    pick = select_daily_pick(subnets)

    assert pick["action"] == "long"
    assert pick["subnet"]["netuid"] == 1
    assert 0 <= pick["score"] <= 100
    assert 0 <= pick["confidence"] <= 1
    assert "audit" in pick
    assert "final_confidence" in pick
    assert set(pick["expert_contributions"].keys()) == {
        "quant", "hype", "contrarian", "technical",
        "signal_contributions", "active_signals", "technical_score",
    }


def test_select_daily_pick_empty_input():
    pick = select_daily_pick([])
    assert pick["subnet"] is None
    assert pick["audit"]["approved"] is False
