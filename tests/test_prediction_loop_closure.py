"""Tests for the closed learning loop (pick → prediction → resolver → weights)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import internal.council.resolver as resolver
import internal.council.weights as weights
from internal.learning import predictions_store
from internal.learning.prediction_loop import record_pick_prediction


@pytest.fixture(autouse=True)
def isolate_paths(tmp_path, monkeypatch):
    pred_path = str(tmp_path / "predictions.json")
    soul_path = str(tmp_path / "soul_map.json")
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", soul_path)
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


def test_record_pick_prediction_persists_pending_row():
    pick = {
        "subnet": {"netuid": 29, "name": "Coldint"},
        "score": 72.0,
        "confidence": 0.68,
        "expert_contributions": {"quant": 0.4, "technical": 0.35, "hype": 0.25},
        "action": "long",
    }
    subnet = {
        "netuid": 29,
        "name": "Coldint",
        "price": 28.5,
        "price_change_24h": 3.2,
    }
    stored = record_pick_prediction(pick, subnet, horizon_type="hour")
    assert stored is not None
    data = predictions_store.load_predictions()
    assert len(data["predictions"]) == 1
    assert data["predictions"][0]["netuid"] == 29
    assert data["predictions"][0]["horizon_type"] == "hour"
    assert data["predictions"][0]["status"] == "pending"
    row = data["predictions"][0]
    assert isinstance(row.get("subnet_snapshot"), dict)
    assert row["subnet_snapshot"].get("price_change_24h") == 3.2
    assert isinstance(row.get("weights_at_creation"), dict)
    assert "quant" in row["weights_at_creation"]


def test_record_pick_prediction_stamps_pump_phase(monkeypatch):
    pick = {
        "subnet": {"netuid": 28, "name": "LOL"},
        "confidence": 0.62,
        "expert_contributions": {"quant": 0.5},
        "action": "long",
    }
    subnet = {"netuid": 28, "name": "LOL", "price": 0.05, "price_change_24h": 4.0}

    monkeypatch.setattr(
        "internal.learning.prediction_loop._pump_phase_at_prediction",
        lambda nu: "ACCUMULATING" if int(nu) == 28 else None,
    )

    stored = record_pick_prediction(pick, subnet, horizon_type="hour")
    assert stored is not None
    row = predictions_store.load_predictions()["predictions"][0]
    assert row.get("phase_at_prediction") == "ACCUMULATING"


def test_record_pick_prediction_dedupes_same_horizon():
    pick = {
        "subnet": {"netuid": 29, "name": "Coldint"},
        "confidence": 0.6,
        "expert_contributions": {"quant": 0.5},
        "action": "long",
    }
    subnet = {"netuid": 29, "name": "Coldint", "price": 10.0, "price_change_24h": 1.0}
    first = record_pick_prediction(pick, subnet, horizon_type="hour")
    second = record_pick_prediction(pick, subnet, horizon_type="hour")
    assert first is not None
    assert second is None
    assert len(predictions_store.load_predictions()["predictions"]) == 1


def test_resolver_closes_loop_and_nudges_weights():
    pick = {
        "subnet": {"netuid": 1, "name": "Alpha"},
        "confidence": 0.7,
        "expert_contributions": {"quant": 0.6, "technical": 0.4},
        "action": "long",
    }
    subnet = {"netuid": 1, "name": "Alpha", "price": 100.0, "price_change_24h": 2.0}
    pred = record_pick_prediction(pick, subnet, horizon_type="hour")
    assert pred is not None

    before = weights.load_weights()["quant"]
    due = dict(pred)
    due["resolve_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    resolved = resolver.resolve_prediction(due, current_price=103.0)
    assert resolved.get("correct") is True
    after = weights.load_weights()["quant"]
    assert after > before


def test_mindmap_feedback_records_learning(tmp_path, monkeypatch):
    soul_path = str(tmp_path / "soul_map.json")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", soul_path)
    from fastapi.testclient import TestClient
    from server import app

    client = TestClient(app)
    resp = client.post(
        "/api/mindmap/feedback",
        json={
            "subnet_id": 1,
            "recommendation": "quant",
            "actual_performance": {"correct_prediction": True},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("learning", {}).get("success") is True
