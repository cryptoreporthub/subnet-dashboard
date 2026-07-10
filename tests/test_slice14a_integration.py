"""Slice 14a integration hardening — learning loop trail + expert normalization."""

from __future__ import annotations

import json

import pytest

from internal.council import resolver
from internal.council.rotation_tokens import build_rotation_tokens_response
from internal.council.weights import SOUL_MAP_PATH, _load_raw


@pytest.mark.parametrize(
    "expert,expected",
    [
        ({"expert": "alpha"}, "quant"),
        ({"expert": "beta"}, "hype"),
        ({"expert": "gamma"}, "dark_horse"),
        ({"expert": "contrarian"}, "dark_horse"),
        ({"signal_source": "technical_rsi"}, "technical"),
    ],
)
def test_normalize_expert_legacy_lanes(expert, expected):
    assert resolver._normalize_expert(expert) == expected


def test_resolve_emits_trail_and_nudges_correct_expert(tmp_path, monkeypatch):
    soul_path = str(tmp_path / "soul_map.json")
    pred_path = str(tmp_path / "predictions.json")
    soul_path_obj = tmp_path / "soul_map.json"
    soul_path_obj.write_text(
        json.dumps(
            {
                "soul_map_state": {"learning_trail": []},
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.0,
                        "hype": 1.0,
                        "dark_horse": 1.0,
                        "technical": 1.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", pred_path)

    import internal.council.weights as weights_mod

    monkeypatch.setattr(weights_mod, "SOUL_MAP_PATH", soul_path)

    prediction = {
        "id": "t1",
        "netuid": 1,
        "name": "Test",
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 10.0,
        "expert": "gamma",
        "horizon_type": "hour",
    }
    resolver.resolve_prediction(prediction, current_price=10.3)
    assert prediction["expert"] == "dark_horse"

    data = _load_raw(soul_path)
    trail = data.get("soul_map_state", {}).get("learning_trail", [])
    assert any(row.get("event_type") == "prediction_resolved" for row in trail)


def test_rotation_tokens_mirror_soul_map(tmp_path, monkeypatch):
    soul_path = str(tmp_path / "soul_map.json")
    (tmp_path / "soul_map.json").write_text(
        json.dumps({"soul_map_state": {"learning_trail": []}}),
        encoding="utf-8",
    )

    import internal.council.weights as weights_mod

    monkeypatch.setattr(weights_mod, "SOUL_MAP_PATH", soul_path)

    def _fake_prices():
        return {
            "hyperliquid": {"price": 1.0, "price_change_24h": 5.0},
            "vvv": {"price": 2.0, "price_change_24h": -1.0},
            "near": {"price": 3.0, "price_change_24h": 0.5},
            "render": {"price": 4.0, "price_change_24h": 1.0},
            "fetch": {"price": 5.0, "price_change_24h": 2.0},
        }

    import internal.council.rotation_tokens as rt

    monkeypatch.setattr(rt, "fetch_rotation_token_prices", _fake_prices)

    resp = build_rotation_tokens_response()
    assert resp["status"] == "success"
    assert len(resp["tokens"]) == 5
    assert resp["tokens"][0].get("conviction") is not None

    data = _load_raw(soul_path)
    snap = data.get("soul_map_state", {}).get("rotation_tokens_snapshot")
    assert snap and snap.get("tokens")
    trail = data.get("soul_map_state", {}).get("learning_trail", [])
    assert any(row.get("event_type") == "rotation_tokens_update" for row in trail)
