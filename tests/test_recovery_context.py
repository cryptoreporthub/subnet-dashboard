from internal.council.recovery_context import build_recovery_context


def _indicators(*, macd="bullish", rsi=42.0, degraded=False):
    return {
        "degraded": degraded,
        "rsi": {"value": rsi, "signal": "oversold" if rsi < 30 else "neutral"},
        "macd": {"crossover": macd, "histogram": 0.12 if macd == "bullish" else -0.12},
    }


def test_recovery_context_requires_real_evidence():
    out = build_recovery_context(
        {"price_change_24h": -15.0},
        _indicators(degraded=True),
        {"source": "unavailable", "closes": [], "lows": [], "volumes": []},
    )

    assert out["classification"] == "inconclusive"
    assert out["trend_context"]["status"] == "unknown"
    assert out["recent_move_vs_trend"]["status"] == "recent_move_only"
    assert out["technical_reversal"]["status"] == "unknown"
    assert out["flow_confirmation"]["status"] == "unknown"
    assert out["lower_lows_without_recovery"]["status"] == "unknown"


def test_recovery_context_marks_recovery_candidate():
    out = build_recovery_context(
        {
            "price_change_24h": -2.0,
            "price_change_7d": -12.0,
            "price_change_30d": -4.0,
            "delegation_incoming_24h": 120.0,
            "delegation_outgoing_24h": 80.0,
        },
        _indicators(macd="bullish", rsi=34.0),
        {
            "source": "taostats",
            "closes": [10.0, 9.0, 9.2, 9.5],
            "lows": [8.8, 8.7, 8.9, 9.1],
            "volumes": [100.0, 100.0, 100.0, 140.0],
        },
    )

    assert out["classification"] == "recovery_candidate"
    assert out["recent_move_vs_trend"]["status"] == "improving"
    assert out["price_structure"]["status"] == "recovery_structure"
    assert out["technical_reversal"]["status"] == "confirmed_reversal"
    assert out["flow_confirmation"]["status"] == "confirmed_positive_flow"


def test_recovery_context_marks_lower_lows_correction_risk():
    out = build_recovery_context(
        {
            "price_change_24h": -8.0,
            "price_change_7d": -14.0,
            "price_change_30d": -22.0,
        },
        _indicators(macd="bearish", rsi=58.0),
        {
            "source": "taostats",
            "closes": [10.0, 9.5, 9.0],
            "lows": [9.5, 9.0, 8.5],
            "volumes": [100.0, 100.0, 100.0],
        },
    )

    assert out["classification"] == "correction_risk"
    assert out["price_structure"]["status"] == "lower_low"
    assert out["lower_lows_without_recovery"]["detected"] is True
    assert out["lower_lows_without_recovery"]["status"] == "high_risk"