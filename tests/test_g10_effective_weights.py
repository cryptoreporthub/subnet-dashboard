"""G10 — regime-aware effective_weights without persistence."""

from __future__ import annotations

import json

import pytest

from internal.council import weights


@pytest.fixture(autouse=True)
def isolate_soul_map(tmp_path, monkeypatch):
    path = str(tmp_path / "soul_map.json")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", path)
    weights.save_weights({"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}, path)
    yield path


def test_effective_weights_applies_risk_on_adjustment(isolate_soul_map):
    market = {"avg_change_24h": 5.0, "gainers": 80, "losers": 10, "breadth": "bullish"}
    eff = weights.effective_weights(market, isolate_soul_map)
    base = weights.load_weights(isolate_soul_map)
    adj = weights.apply_regime_adjustment(base, "risk_on")
    assert eff == adj
    assert eff["hype"] > base["hype"]


def test_effective_weights_applies_risk_off_adjustment(isolate_soul_map):
    market = {"avg_change_24h": -5.0, "gainers": 10, "losers": 80, "breadth": "bearish"}
    eff = weights.effective_weights(market, isolate_soul_map)
    base = weights.load_weights(isolate_soul_map)
    adj = weights.apply_regime_adjustment(base, "risk_off")
    assert eff == adj
    assert eff["hype"] < base["hype"]


def test_effective_weights_chop_unchanged(isolate_soul_map):
    market = {"avg_change_24h": 0.5, "gainers": 50, "losers": 50}
    eff = weights.effective_weights(market, isolate_soul_map)
    base = weights.load_weights(isolate_soul_map)
    expected = weights.apply_regime_adjustment(base, "chop")
    assert eff == expected


def test_effective_weights_does_not_persist(isolate_soul_map):
    market = {"avg_change_24h": 10.0, "gainers": 90, "losers": 5, "breadth": "bullish"}
    before = dict(weights.load_weights(isolate_soul_map))
    weights.effective_weights(market, isolate_soul_map)
    after = dict(weights.load_weights(isolate_soul_map))
    assert after == before


def test_effective_weights_no_l1_normalize(isolate_soul_map):
    weights.save_weights({"quant": 2.0, "hype": 0.5, "dark_horse": 1.0, "technical": 1.0}, isolate_soul_map)
    market = {"avg_change_24h": 5.0, "gainers": 80, "losers": 10}
    eff = weights.effective_weights(market, isolate_soul_map)
    total = sum(eff.values())
    assert total != pytest.approx(1.0, abs=0.01)
