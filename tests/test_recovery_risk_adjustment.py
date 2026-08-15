"""Long-pick scoring distinguishes recovery from correction (task path tests)."""

from internal.council import state_vector
from internal.council.recovery_context import (
    ELEVATED_RISK_HAIRCUT,
    HIGH_RISK_HAIRCUT,
    build_recovery_context,
    recovery_risk_adjustment,
)


def _indicators(*, macd="bullish", rsi=42.0, degraded=False):
    return {
        "degraded": degraded,
        "rsi": {"value": rsi, "signal": "oversold" if rsi < 30 else "neutral"},
        "macd": {"crossover": macd, "histogram": 0.12 if macd == "bullish" else -0.12},
    }


CORRECTION_SN = {
    "netuid": 42,
    "price_change_24h": -8.0,
    "price_change_7d": -14.0,
    "price_change_30d": -22.0,
    "delegation_incoming_24h": 50.0,
    "delegation_outgoing_24h": 90.0,
}

CORRECTION_HISTORY = {
    "source": "taostats",
    "closes": [10.0, 9.5, 9.0],
    "highs": [10.5, 10.0, 9.5],
    "lows": [9.5, 9.0, 8.5],
    "volumes": [100.0, 100.0, 100.0],
    "timestamps": [],
}

RECOVERY_SN = {
    "netuid": 42,
    "price_change_24h": -2.0,
    "price_change_7d": -12.0,
    "price_change_30d": -4.0,
    "delegation_incoming_24h": 120.0,
    "delegation_outgoing_24h": 80.0,
}

RECOVERY_HISTORY = {
    "source": "taostats",
    "closes": [10.0, 9.0, 9.2, 9.5],
    "highs": [10.5, 9.6, 9.8, 10.0],
    "lows": [8.8, 8.7, 8.9, 9.1],
    "volumes": [100.0, 100.0, 100.0, 140.0],
    "timestamps": [],
}


# ---------------------------------------------------------------------------
# Adjustment helper
# ---------------------------------------------------------------------------
def test_high_risk_correction_gets_full_haircut():
    ctx = build_recovery_context(
        CORRECTION_SN, _indicators(macd="bearish", rsi=58.0), CORRECTION_HISTORY
    )
    adj = recovery_risk_adjustment(ctx)

    assert ctx["classification"] == "correction_risk"
    assert adj["applied"] is True
    assert adj["haircut"] == HIGH_RISK_HAIRCUT
    assert adj["reason"] == "prolonged_downtrend_no_recovery_confirmation"


def test_elevated_risk_without_lower_lows_gets_smaller_haircut():
    # Downtrend but no lower-lows structure and no bearish MACD confirmation.
    sn = dict(CORRECTION_SN)
    history = {
        "source": "taostats",
        "closes": [10.0, 9.5, 9.4],
        "highs": [10.5, 10.0, 9.9],
        "lows": [9.0, 9.1, 9.05],
        "volumes": [100.0, 100.0, 100.0],
        "timestamps": [],
    }
    ctx = build_recovery_context(sn, _indicators(macd=None, rsi=45.0), history)
    adj = recovery_risk_adjustment(ctx)

    assert ctx["classification"] == "correction_risk"
    assert adj["applied"] is True
    assert adj["haircut"] == ELEVATED_RISK_HAIRCUT
    assert adj["reason"] == "correction_risk_elevated"


def test_recovery_candidate_is_preserved_without_haircut():
    ctx = build_recovery_context(
        RECOVERY_SN, _indicators(macd="bullish", rsi=34.0), RECOVERY_HISTORY
    )
    adj = recovery_risk_adjustment(ctx)

    assert ctx["classification"] == "recovery_candidate"
    assert adj["applied"] is False
    assert adj["haircut"] == 0.0
    assert adj["reason"] == "recovery_evidence_present"


def test_unknown_evidence_never_triggers_haircut():
    adj = recovery_risk_adjustment(
        build_recovery_context({"price_change_24h": -15.0}, {"degraded": True}, None)
    )
    assert adj["applied"] is False
    assert adj["haircut"] == 0.0

    assert recovery_risk_adjustment(None)["applied"] is False
    assert recovery_risk_adjustment({})["applied"] is False


# ---------------------------------------------------------------------------
# Day (long-pick) scorer integration
# ---------------------------------------------------------------------------
def _score_day(monkeypatch, sn, indicators, history):
    monkeypatch.setattr(state_vector, "_get_price_history", lambda *_: history)
    monkeypatch.setattr(state_vector, "_compute_technical_indicators", lambda *_: indicators)
    return state_vector.score_subnet_for_day(sn, {"skip_pump_overlay": True})


def test_day_score_takes_haircut_on_correction_risk(monkeypatch):
    result = _score_day(
        monkeypatch,
        CORRECTION_SN,
        _indicators(macd="bearish", rsi=58.0),
        CORRECTION_HISTORY,
    )

    adj = result["recovery_risk_adjustment"]
    assert result["recovery_context"]["classification"] == "correction_risk"
    assert adj["applied"] is True
    assert adj["haircut"] == HIGH_RISK_HAIRCUT
    assert adj["score_after"] == result["total_score"]
    assert adj["score_after"] <= adj["score_before"]
    if adj["score_before"] > 0:
        assert adj["score_after"] < adj["score_before"]
        assert adj["score_after"] == round(
            adj["score_before"] * (1.0 - HIGH_RISK_HAIRCUT), 2
        )


def test_day_score_preserves_recovery_candidate(monkeypatch):
    result = _score_day(
        monkeypatch,
        RECOVERY_SN,
        _indicators(macd="bullish", rsi=34.0),
        RECOVERY_HISTORY,
    )

    adj = result["recovery_risk_adjustment"]
    assert result["recovery_context"]["classification"] == "recovery_candidate"
    assert adj["applied"] is False
    assert adj["haircut"] == 0.0
    assert "score_before" not in adj
