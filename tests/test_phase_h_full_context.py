"""Phase H-full Agent A — premium dashboard context builders."""

from __future__ import annotations

from internal.analytics.root_context import build_market_intelligence, build_staking_analytics
from internal.learning.dashboard_context import build_learning_dashboard_context
from internal.learning.premium_dashboard_builders import (
    build_simivision_picks,
    build_undervalued_radar,
)


def _sample_subnets():
    return [
        {
            "netuid": 1,
            "name": "Alpha",
            "price": 100.0,
            "emission": 2.0,
            "apy": 35.0,
            "volume": 500_000.0,
            "price_change_24h": 5.0,
        },
        {
            "netuid": 2,
            "name": "Beta",
            "price": 50.0,
            "emission": 0.5,
            "apy": 12.0,
            "volume": 100_000.0,
            "price_change_24h": -3.0,
        },
        {
            "netuid": 3,
            "name": "Gamma",
            "price": 10.0,
            "emission": 1.0,
            "apy": 45.0,
            "volume": 50_000.0,
            "price_change_24h": 1.0,
        },
    ]


def test_simivision_picks_sell_suppresses_hot():
    subnets = _sample_subnets()
    picks = build_simivision_picks(subnets)
    assert len(picks) <= 6
    for pick in picks:
        if pick["sell"].get("active"):
            assert pick["hot"].get("active") is False
            assert pick["hot"].get("suppressed_by") == "SELL ALERT"


def test_undervalued_radar_returns_ranked_rows():
    rows = build_undervalued_radar(_sample_subnets())
    assert len(rows) <= 8
    assert rows[0]["rank"] == 1
    assert "undervalued_score" in rows[0]


def test_market_intelligence_breadth():
    summary = build_market_intelligence(_sample_subnets())
    assert summary["total"] == 3
    assert summary["breadth"] in {"bullish", "bearish", "neutral"}


def test_staking_analytics_top_yield():
    staking = build_staking_analytics(_sample_subnets())
    assert staking["subnet_count"] == 3
    assert len(staking["top_yield"]) >= 1


def test_learning_dashboard_context_includes_h_full_keys():
    ctx = build_learning_dashboard_context(_sample_subnets(), {"tao_change_24h": 0.0})
    for key in (
        "simivision_picks",
        "undervalued_radar",
        "technical_indicators",
        "signal_impact",
        "social_sentiment",
        "market_intelligence",
        "staking_analytics",
    ):
        assert key in ctx
