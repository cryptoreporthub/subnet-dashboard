"""B5 candle gate checks for council technical scoring."""

from internal.council.state_vector import (
    _compute_technical_indicators,
    _compute_technical_score,
    _get_price_history,
)


def test_price_history_unavailable_without_cache(monkeypatch):
    monkeypatch.setattr("internal.council.state_vector._load_price_cache", lambda: {})
    hist = _get_price_history(1, {"netuid": 1, "price": 1.0})
    assert hist["source"] == "unavailable"
    assert hist["closes"] == []


def test_technical_score_degraded_without_history(monkeypatch):
    monkeypatch.setattr("internal.council.state_vector._load_price_cache", lambda: {})
    sn = {"netuid": 1, "price": 1.0, "price_change_24h": 2.0}
    indicators = _compute_technical_indicators(sn)
    assert indicators.get("degraded") is True
    score = _compute_technical_score(sn, "hour")
    assert score["technical_score"] == 0.5
    assert score.get("degraded") is True
    assert score["active_signals"] == []
