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


def test_resolver_defers_to_weights_for_delta_constants():
    """resolver.py no longer owns its own learning delta constants.
    weights.py is the single source of truth for _LEARNING_DELTA_CORRECT / _LEARNING_DELTA_WRONG.
    """
    import internal.council.weights as weights_mod

    assert not hasattr(resolver, "_LEARNING_DELTA_CORRECT"), (
        "resolver._LEARNING_DELTA_CORRECT should not exist — weights.py is authoritative"
    )
    assert not hasattr(resolver, "_LEARNING_DELTA_WRONG"), (
        "resolver._LEARNING_DELTA_WRONG should not exist — weights.py is authoritative"
    )
    # weights.py defines the asymmetric pair used everywhere.
    assert weights_mod._LEARNING_DELTA_CORRECT == 0.02
    assert weights_mod._LEARNING_DELTA_WRONG == -0.03
    assert weights_mod._LEARNING_MIN_WEIGHT == 0.1


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


def test_wrong_pick_applies_penalty():
    """A wrong prediction applies the asymmetric wrong-delta (-0.03) from weights.py."""
    before = weights.load_weights()["quant"]
    pred = {
        "reference_price": 100.0,
        "predicted_pct": 5.0,
        "direction": "up",
        "expert": "quant",
    }
    resolver.resolve_prediction(pred, current_price=95.0)
    after = weights.load_weights()["quant"]
    assert after == pytest.approx(before + weights._LEARNING_DELTA_WRONG, abs=1e-4)
    assert after >= weights._LEARNING_MIN_WEIGHT
