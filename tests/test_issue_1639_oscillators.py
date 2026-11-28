"""#1639 — oscillator schema, signal-impact honesty, shared convergence contract."""

from __future__ import annotations

from fastapi.testclient import TestClient

from internal.analytics.root_context import _safe_indicators_convergence
from internal.council.state_vector import (
    _compute_cci,
    _compute_mfi,
    _compute_signal_impact,
    _compute_technical_indicators,
    _compute_williams_r,
    _degraded_technical_indicators,
    _detect_oversold_convergence,
    _compute_hot_signals,
    _compute_sell_signals,
)
from internal.indicators.convergence import build_indicators_convergence
from server import app


def _live_shell(**overrides):
    base = {
        "rsi": {"value": 50.0, "signal": "neutral"},
        "stochastic": {"k": 50.0, "d": 50.0, "signal": "neutral"},
        "mfi": {"value": 50.0, "signal": "neutral"},
        "cci": {"value": 0.0, "signal": "neutral"},
        "williams": {"value": -50.0, "signal": "neutral"},
        "bollinger": {"upper": 1, "middle": 1, "lower": 1, "width": 0.1, "signal": "neutral"},
        "keltner": {"signal": "neutral"},
        "macd": {"histogram": 0.0, "crossover": "neutral"},
        "degraded": False,
    }
    base.update(overrides)
    return base


def test_raw_oscillator_value_keys_no_score_collision():
    degraded = _degraded_technical_indicators({"source": "unavailable", "closes": []})
    assert isinstance(degraded.get("williams"), dict)
    assert isinstance(degraded.get("williams_r"), float)
    assert degraded["mfi"]["value"] == 50.0
    assert degraded["cci"]["value"] == 0.0
    assert degraded["bollinger"]["width"] == 0.0
    assert degraded["macd"]["crossover"] == "neutral"


def test_williams_oversold_counts_in_convergence():
    indicators = _live_shell(williams={"value": -85.0, "signal": "oversold"})
    conv = _detect_oversold_convergence(indicators)
    assert "williams" in conv["indicators"]
    assert conv["total"] == 7


def test_mfi_cci_and_bollinger_signal_impact_use_live_values():
    indicators = _live_shell(
        mfi={"value": 12.0, "signal": "oversold"},
        cci={"value": -150.0, "signal": "oversold"},
        bollinger={"width": 2.34, "signal": "oversold"},
    )
    sn = {"netuid": 1, "price_change_24h": 0.0, "apy": 1.0, "emission": 0.1}
    hot = _compute_hot_signals(sn, indicators, _detect_oversold_convergence(indicators))
    sell = _compute_sell_signals(sn, indicators, {"convergent": False})
    si = _compute_signal_impact(sn, indicators, hot, sell)
    joined = " ".join(i["description"] for i in si["impacts"])
    assert "MFI 12.0 oversold" in joined
    assert "CCI -150.0 deeply oversold" in joined
    assert "width 2.34" in joined


def test_degraded_signal_impact_marks_oscillators_unavailable():
    indicators = _degraded_technical_indicators({"source": "unavailable", "closes": []})
    sn = {"netuid": 1, "price_change_24h": 0.0, "apy": 1.0, "emission": 0.1}
    si = _compute_signal_impact(
        sn, indicators, {"active": False}, {"active": False},
    )
    oscillator = [
        i for i in si["impacts"]
        if i["signal_type"]
        in {
            "rsi_crossover",
            "macd_cross",
            "stochastic_reversal",
            "bollinger_squeeze",
            "mfi_divergence",
            "cci_extreme",
            "williams_r_reversal",
        }
    ]
    assert len(oscillator) == 7
    assert all("no price history" in i["description"] for i in oscillator)


def test_williams_mfi_cci_compute_helpers_emit_value_key():
    closes = [float(10 - i * 0.05) for i in range(40)]
    highs = [c + 0.2 for c in closes]
    lows = [c - 0.2 for c in closes]
    volumes = [1000.0] * len(closes)
    assert "value" in _compute_williams_r(highs, lows, closes)
    assert "value" in _compute_mfi(highs, lows, closes, volumes)
    assert "value" in _compute_cci(highs, lows, closes)


def test_build_indicators_convergence_matches_root_and_api(monkeypatch):
    import internal.indicators.convergence as conv

    subnets = [{"netuid": 9, "name": "SN9", "emission": 2.0}]
    monkeypatch.setattr(
        conv,
        "_compute_technical_indicators",
        lambda sn: {"degraded": True, "history_source": "unavailable"},
    )
    monkeypatch.setattr(conv, "_get_price_history", lambda n, sn: {"closes": [], "source": "unavailable"})
    payload = build_indicators_convergence(subnets)
    root = _safe_indicators_convergence(subnets)
    assert payload == root
    assert payload["data_available"] is False
    assert payload["subnets"][0]["degraded"] is True
    assert payload["subnets"][0]["oversold"]["reason"] == "no_ohlcv"


def test_server_rendered_indicators_degraded_skip_neutral_badge():
    from server import app as fastapi_app

    templates = fastapi_app.state.templates if hasattr(fastapi_app.state, "templates") else None
    if templates is None:
        from server import templates as tpl
        templates = tpl
    html = templates.get_template("partials/premium/indicators.html").render(
        ti_rows=[
            {
                "netuid": 3,
                "name": "Test",
                "degraded": True,
                "spark_closes": [],
                "oversold": {"convergent": False, "count": 0, "reason": "no_ohlcv"},
                "overbought": {"convergent": False, "count": 0, "reason": "no_ohlcv"},
            }
        ]
    )
    assert "Awaiting price history" in html
    assert "Signal heat" not in html
    assert "NEUTRAL" not in html


def test_technical_indicators_live_payload_schema(monkeypatch):
    monkeypatch.setattr("internal.council.state_vector._load_price_cache", lambda: {})
    closes = [float(50 + (i % 5) - 2) for i in range(60)]
    hist = {
        "closes": closes,
        "highs": [c + 1 for c in closes],
        "lows": [c - 1 for c in closes],
        "volumes": [100.0] * len(closes),
        "source": "cache",
    }
    monkeypatch.setattr("internal.council.state_vector._get_price_history", lambda *a, **k: hist)
    indicators = _compute_technical_indicators({"netuid": 5, "price": closes[-1]})
    assert indicators.get("degraded") is not True
    for key in ("mfi", "cci", "williams"):
        assert isinstance(indicators[key], dict)
        assert "value" in indicators[key]
    assert isinstance(indicators.get("williams_r"), float)