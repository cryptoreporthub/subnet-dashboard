"""#1639 — oscillator schema, signal-impact honesty, shared convergence contract."""

from __future__ import annotations

import pytest

from internal.analytics.root_context import _safe_indicators_convergence
from internal.council.state_vector import (
    _compute_cci,
    _compute_mfi,
    _compute_signal_impact,
    _compute_technical_indicators,
    _compute_williams_r,
    _degraded_technical_indicators,
    _detect_oversold_convergence,
    _detect_overbought_convergence,
    _compute_hot_signals,
    _compute_sell_signals,
)
from internal.indicators.convergence import build_indicators_convergence, indicators_convergence_error_payload
from server import app, templates


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


def test_williams_overbought_emits_bearish_reversal_impact():
    """F8: sell path must receive overbought convergence (not oversold) so Williams counts toward bearish setup."""
    indicators = _live_shell(
        williams={"value": -10.0, "signal": "overbought"},
        rsi={"value": 80.0, "signal": "overbought"},
        stochastic={"k": 90.0, "d": 85.0, "signal": "overbought"},
        mfi={"value": 85.0, "signal": "overbought"},
    )
    overbought_conv = _detect_overbought_convergence(indicators)
    assert "williams" in overbought_conv["indicators"]
    assert overbought_conv["type"] == "overbought"
    assert overbought_conv["convergent"] is True

    sn = {"netuid": 1, "price_change_24h": 0.0, "apy": 1.0, "emission": 0.1}
    sell = _compute_sell_signals(sn, indicators, overbought_conv)
    assert any("Overbought convergence" in r for r in sell["reasons"])

    si = _compute_signal_impact(sn, indicators, {"active": False}, sell)
    williams = next(i for i in si["impacts"] if i["signal_type"] == "williams_r_reversal")
    assert williams["direction"] == "bearish"
    assert "Williams %R -10.0 overbought" in williams["description"]


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


def test_build_indicators_convergence_matches_root_and_api(client, monkeypatch):
    import internal.indicators.convergence as conv
    import server

    subnets = [{"netuid": 9, "name": "SN9", "emission": 2.0}]
    monkeypatch.setattr(server, "_get_subnets_with_source", lambda: (subnets, "registry"))
    monkeypatch.setattr(
        conv,
        "_compute_technical_indicators",
        lambda sn, **kw: {"degraded": True, "history_source": "unavailable"},
    )
    monkeypatch.setattr(conv, "_get_price_history", lambda n, sn: {"closes": [], "source": "unavailable"})
    payload = build_indicators_convergence(subnets)
    root = _safe_indicators_convergence(subnets)
    assert payload == root
    assert client.get("/api/indicators-convergence").json() == payload
    assert payload["data_available"] is False
    assert payload["subnets"][0]["degraded"] is True
    assert payload["subnets"][0]["oversold"]["reason"] == "no_ohlcv"


def test_indicators_convergence_error_payload_shape():
    body = indicators_convergence_error_payload(RuntimeError("boom"))
    assert body["data_available"] is False
    assert body["source"] == "none"
    assert body["reason"] == "error"
    assert body["error"] == "indicators_convergence_unavailable"
    assert "boom" not in str(body)


def test_degraded_rows_omit_spark_closes(monkeypatch):
    import internal.indicators.convergence as conv

    subnets = [{"netuid": 1, "name": "SN1", "emission": 1.0}]
    monkeypatch.setattr(
        conv,
        "_compute_technical_indicators",
        lambda sn, **kw: {"degraded": True, "history_source": "cache"},
    )
    monkeypatch.setattr(
        conv,
        "_get_price_history",
        lambda n, sn: {"closes": [1.0, 1.1, 1.2], "source": "cache"},
    )
    row = build_indicators_convergence(subnets)["subnets"][0]
    assert row["degraded"] is True
    assert row["spark_closes"] == []


def test_build_indicators_convergence_survives_hist_none(monkeypatch):
    import internal.indicators.convergence as conv

    subnets = [{"netuid": 2, "name": "SN2", "emission": 1.0}]
    monkeypatch.setattr(conv, "_get_price_history", lambda n, sn: None)
    monkeypatch.setattr(
        conv,
        "_compute_technical_indicators",
        lambda sn, **kw: {"degraded": True, "history_source": "no_ohlcv"},
    )
    payload = build_indicators_convergence(subnets)
    assert len(payload["subnets"]) == 1


def test_build_indicators_convergence_sorts_with_null_emission(monkeypatch):
    import internal.indicators.convergence as conv

    subnets = [
        {"netuid": 1, "name": "A", "emission": None, "apy": 1.0},
        {"netuid": 2, "name": "B", "emission": 2.0, "apy": 0.0},
    ]
    monkeypatch.setattr(
        conv,
        "_get_price_history",
        lambda n, sn: {"closes": [], "source": "unavailable"},
    )
    monkeypatch.setattr(
        conv,
        "_compute_technical_indicators",
        lambda sn, **kw: {"degraded": True, "history_source": "unavailable"},
    )
    rows = build_indicators_convergence(subnets)["subnets"]
    assert rows[0]["netuid"] == 2


def test_root_safe_convergence_matches_error_payload(monkeypatch):
    import internal.indicators.convergence as conv

    monkeypatch.setattr(conv, "build_indicators_convergence", lambda subnets: (_ for _ in ()).throw(ValueError("secret-path")))
    from internal.analytics.root_context import _safe_indicators_convergence

    body = _safe_indicators_convergence([])
    assert body == indicators_convergence_error_payload(ValueError("secret-path"))
    assert "secret" not in str(body)


def test_template_all_degraded_uses_visible_slice_only():
    live_tail = {
        "netuid": 99,
        "name": "Live",
        "degraded": False,
        "spark_closes": [1.0, 1.1],
        "oversold": {"count": 0, "total": 7},
        "overbought": {"count": 0, "total": 7},
    }
    rows = [{"netuid": i, "name": f"SN{i}", "degraded": True, "spark_closes": []} for i in range(6)]
    rows.append(live_tail)
    html = templates.get_template("partials/premium/indicators.html").render(ti_rows=rows)
    assert "Oscillator panel awaiting price history" in html

    mixed_visible = [{"netuid": i, "name": f"SN{i}", "degraded": True, "spark_closes": []} for i in range(5)]
    mixed_visible.append(live_tail)
    html_mixed = templates.get_template("partials/premium/indicators.html").render(ti_rows=mixed_visible)
    assert "Oscillator panel awaiting price history" not in html_mixed


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


def test_server_rendered_indicators_degraded_skip_neutral_badge():
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