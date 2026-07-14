"""Full learning loop: pick → prediction (with impact) → resolve → dial nudge → trail."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import internal.council.resolver as resolver
import internal.council.weights as weights
from internal.learning import predictions_store
from internal.learning.prediction_loop import record_pick_prediction


def test_full_loop_stamps_impact_and_nudges_strength(tmp_path, monkeypatch):
    pred_path = str(tmp_path / "predictions.json")
    soul_path = str(tmp_path / "soul_map.json")
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", soul_path)
    monkeypatch.delenv("IMPACT_STRENGTH", raising=False)
    (tmp_path / "soul_map.json").write_text(
        json.dumps(
            {
                "soul_map_state": {"learning_trail": []},
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.0,
                        "hype": 1.0,
                        "dark_horse": 1.0,
                        "technical": 1.0,
                    },
                    "impact_strength": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )

    pick = {
        "subnet": {"netuid": 15, "name": "Thin"},
        "score": 70.0,
        "confidence": 0.7,
        "final_confidence": 0.7,
        "expert_contributions": {"quant": 0.5, "hype": 0.3, "technical": 0.2},
        "action": "long",
        "impact": {
            "tier": "small",
            "strength": 1.0,
            "relative_flow": 0.2,
            "ref_impact_pct": 0.25,
            "summary": "small-cap: 50 TAO ≈ 0.25% of float",
        },
    }
    subnet = {
        "netuid": 15,
        "name": "Thin",
        "price": 10.0,
        "market_cap": 20_000,
        "volume": 5_000,
        "price_change_24h": 4.0,
    }

    stored = record_pick_prediction(pick, subnet, horizon_type="hour")
    assert stored is not None
    assert stored.get("impact_tier") == "small"
    assert stored.get("impact_strength_at_creation") == 1.0
    assert stored.get("market_impact", {}).get("tier") == "small"
    assert "impact_strength" in (stored.get("learning_state_at_creation") or {})

    before = weights.load_impact_strength()
    due = dict(stored)
    due["resolve_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    resolved = resolver.resolve_prediction(due, current_price=10.5)
    assert resolved.get("correct") is True

    after = weights.load_impact_strength()
    # Small-tier correct → strength rises
    assert after == round(before + 0.02, 4)
    assert resolved.get("impact_strength_after") == after

    soul = json.loads((tmp_path / "soul_map.json").read_text())
    trail = soul.get("soul_map_state", {}).get("learning_trail", [])
    assert any(row.get("event_type") == "prediction_resolved" for row in trail)
    assert any(
        row.get("event_type") == "weight_change"
        and (row.get("judge") == "impact_strength" or (row.get("evidence") or {}).get("dial") == "impact_strength")
        for row in trail
    )


def test_large_cap_correct_lowers_strength_in_loop(tmp_path, monkeypatch):
    pred_path = str(tmp_path / "predictions.json")
    soul_path = str(tmp_path / "soul_map.json")
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", soul_path)
    monkeypatch.delenv("IMPACT_STRENGTH", raising=False)
    (tmp_path / "soul_map.json").write_text(
        json.dumps(
            {
                "soul_map_state": {"learning_trail": []},
                "adversarial_state": {
                    "council_weights": {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
                    "impact_strength": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )

    pick = {
        "subnet": {"netuid": 64, "name": "Chutes"},
        "confidence": 0.7,
        "expert_contributions": {"quant": 0.6},
        "action": "long",
        "impact": {"tier": "large", "strength": 1.0},
    }
    subnet = {
        "netuid": 64,
        "name": "Chutes",
        "price": 1.0,
        "market_cap": 400_000,
        "volume": 2_000,
        "price_change_24h": 2.0,
    }
    stored = record_pick_prediction(pick, subnet, horizon_type="day")
    assert stored is not None
    due = dict(stored)
    due["resolve_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    resolver.resolve_prediction(due, current_price=1.05)
    assert weights.load_impact_strength() == 0.98
