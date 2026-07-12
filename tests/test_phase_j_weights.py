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


def test_symmetric_weight_deltas():
    assert resolver._LEARNING_DELTA_CORRECT == 0.02
    assert resolver._LEARNING_DELTA_WRONG == -0.02
    assert resolver._LEARNING_MIN_WEIGHT == 0.3


def test_replay_mode_pauses_weight_nudges():
    before = weights.load_weights()["quant"]
    pred = {
        "reference_price": 100.0,
        "predicted_pct": 5.0,
        "direction": "up",
        "expert": "quant",
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
    }
    resolver.resolve_prediction(pred, current_price=95.0)
    after = weights.load_weights()["quant"]
    assert after == pytest.approx(before - 0.02, abs=1e-4)
    assert after >= resolver._LEARNING_MIN_WEIGHT
