"""Call reasons should lead with live signal-impact content, not only APY/emission."""

from __future__ import annotations

from internal.council.daily_pick import select_daily_pick
from internal.council.state_vector import (
    _compute_signal_impact,
    _compute_technical_indicators,
    _detect_oversold_convergence,
    _compute_hot_signals,
    _compute_sell_signals,
    pick_reasons,
)


def _sn(**overrides):
    base = {
        "netuid": 64,
        "name": "Chutes",
        "symbol": "CHUTES",
        "price": 40.0,
        "volume": 50_000,
        "market_cap": 8_000_000,
        "emission": 5.0,
        "apy": 45.0,
        "price_change_24h": 9.0,
        "price_change_7d": 12.0,
        "status": "active",
    }
    base.update(overrides)
    return base


def test_pick_reasons_prefer_directional_signal_descriptions():
    sn = _sn()
    indicators = _compute_technical_indicators(sn)
    convergence = _detect_oversold_convergence(indicators)
    hot = _compute_hot_signals(sn, indicators, convergence)
    sell = _compute_sell_signals(sn, indicators, convergence)
    si = _compute_signal_impact(sn, indicators, hot, sell)
    # Force a loud directional impact so we don't depend on OHLCV history.
    si = dict(si)
    si["impacts"] = [
        {
            "signal_type": "momentum_shift",
            "description": "24h change +9.0% momentum",
            "direction": "bullish",
            "magnitude_pct": 4.5,
            "confidence": 72,
        },
        {
            "signal_type": "rsi_crossover",
            "description": "RSI 28.0 oversold — mean-reversion bounce",
            "direction": "bullish",
            "magnitude_pct": 2.0,
            "confidence": 75,
        },
        {
            "signal_type": "macd_cross",
            "description": "MACD unavailable",
            "direction": "neutral",
            "magnitude_pct": 0.5,
            "confidence": 50,
        },
    ]
    si["net_predicted_pct"] = 3.2
    si["net_predicted_pct_raw"] = 2.0

    reasons = pick_reasons(sn, si)
    assert reasons
    joined = " ".join(reasons).lower()
    assert "momentum" in joined or "oversold" in joined
    assert "unavailable" not in joined
    # Impact float-share line still present for sized names.
    assert any("cap" in r.lower() or "tao" in r.lower() for r in reasons)


def test_daily_pick_reasons_use_scored_signal_impact():
    sn = _sn(netuid=19, name="Inference", market_cap=500_000)
    pick = select_daily_pick([sn])
    assert pick["reasons"]
    assert pick["prediction"] is not None
    # Expert/source derived from signal impact, not hard-coded quant/council_day_pick only.
    assert pick["prediction"]["signal_source"]
    assert pick["prediction"]["expert"] in (
        "quant",
        "hype",
        "dark_horse",
        "technical",
        "unclassified",
    )
    # At least one reason should not be the generic accumulation fallback alone.
    assert pick["reasons"] != ["Balanced metrics — accumulation phase"]


def test_skips_neutral_filler_impacts():
    sn = _sn(price_change_24h=0.2, emission=0.1, apy=5.0, market_cap=0)
    si = {
        "impacts": [
            {
                "signal_type": "market_breadth",
                "description": "Market breadth filler",
                "direction": "bullish",
                "magnitude_pct": 0.6,
                "confidence": 50,
            },
            {
                "signal_type": "rsi_crossover",
                "description": "RSI 50.0 neutral — no edge",
                "direction": "neutral",
                "magnitude_pct": 0.8,
                "confidence": 50,
            },
        ],
        "net_predicted_pct": 0.1,
        "net_predicted_pct_raw": 0.1,
    }
    reasons = pick_reasons(sn, si)
    joined = " ".join(reasons).lower()
    assert "filler" not in joined
    assert "no edge" not in joined
