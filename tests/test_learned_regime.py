"""§21 L7 — learned regime adjustment from resolved predictions."""

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


def test_learned_regime_falls_back_to_static_without_samples(isolate_soul_map, monkeypatch):
    monkeypatch.setattr(weights, "_expert_hits_by_regime", lambda: {})
    learned = weights.learned_regime_adjustment("risk_on")
    assert learned == weights.REGIME_ADJUSTMENTS["risk_on"]


def test_learned_regime_nudges_when_enough_samples(isolate_soul_map, monkeypatch):
    monkeypatch.setattr(
        weights,
        "_expert_hits_by_regime",
        lambda: {
            "risk_on": {
                "quant": [True] * 6,
                "hype": [False] * 6,
            }
        },
    )
    learned = weights.learned_regime_adjustment("risk_on")
    static = weights.REGIME_ADJUSTMENTS["risk_on"]
    assert learned["quant"] >= static["quant"]
    assert learned["hype"] <= static["hype"]
