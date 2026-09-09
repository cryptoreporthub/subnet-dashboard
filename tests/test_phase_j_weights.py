"""Phase J — symmetric weights and replay pause."""

from __future__ import annotations

import json

import pytest

import internal.council.resolver as resolver
import internal.council.weights as weights


@pytest.fixture(autouse=True)
def isolate_weights(tmp_path, monkeypatch):
    soul_path = str(tmp_path / "soul_map.json")
    soul_path_obj = tmp_path / "soul_map.json"
    soul_path_obj.write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.0,
                        "hype": 1.0,
                        "dark_horse": 1.0,
                        "technical": 1.0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", soul_path)
    monkeypatch.setattr("internal.judges.weights.SOUL_MAP_PATH", soul_path)


def test_learning_constants_live_in_weights_module():
    # P0.4: resolver must not carry a second divergent learning-constant copy.
    for name in (
        "_LEARNING_DELTA_CORRECT",
        "_LEARNING_DELTA_WRONG",
        "_LEARNING_MIN_WEIGHT",
        "_LEARNING_MAX_WEIGHT",
    ):
        assert not hasattr(resolver, name), name
    assert weights._LEARNING_DELTA_CORRECT == 0.02
    assert weights._LEARNING_DELTA_WRONG == -0.03
    assert weights._LEARNING_MIN_WEIGHT == 0.1
    assert weights._LEARNING_MAX_WEIGHT == 2.0


def test_replay_mode_pauses_weight_nudges():
    before = weights.load_weights()["quant"]
    pred = {
        "reference_price": 100.0,
        "predicted_pct": 5.0,
        "direction": "up",
        "expert": "quant",
        "pick_source": "council",
        "signal_source": "emission_momentum",
        "active_signals": ["emission_momentum"],
        "signal_impact": {
            "impacts": [{"signal_type": "emission_momentum", "magnitude_pct": 1.0}]
        },
    }
    with resolver.replay_mode(True):
        resolver.resolve_prediction(pred, current_price=105.0)
    after = weights.load_weights()["quant"]
    assert after == before


def test_wrong_pick_applies_symmetric_penalty():
    before = weights.load_weights()["quant"]
    pred = {
        "reference_price": 100.0,
        "predicted_pct": 5.0,
        "direction": "up",
        "expert": "quant",
        "pick_source": "council",
        "signal_source": "emission_momentum",
        "active_signals": ["emission_momentum"],
        "signal_impact": {
            "impacts": [{"signal_type": "emission_momentum", "magnitude_pct": 1.0}]
        },
    }
    resolver.resolve_prediction(pred, current_price=95.0)
    after = weights.load_weights()["quant"]
    assert after == pytest.approx(before + weights._LEARNING_DELTA_WRONG, abs=1e-4)
    assert after >= weights._LEARNING_MIN_WEIGHT
