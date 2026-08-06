"""Tests for the closed learning loop (pick → prediction → resolver → weights)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

import internal.council.resolver as resolver
import internal.council.resolver_scheduler as resolver_scheduler
import internal.council.weights as weights
from internal.learning import predictions_store
from internal.learning.prediction_loop import record_pick_prediction

_store_lock = threading.Lock()


def _stop_prediction_background_jobs() -> None:
    """Contract tests may start resolver/pick schedulers; stop stray ticks."""
    resolver_scheduler.stop_prediction_resolver_scheduler()
    try:
        from internal.council.pick_scheduler import stop_pick_schedulers

        stop_pick_schedulers()
    except Exception:
        pass
    try:
        from internal.council.selector_scheduler import stop_selector_scheduler

        stop_selector_scheduler()
    except Exception:
        pass
    try:
        from internal.pump.scheduler import stop_pump_ladder_scheduler

        stop_pump_ladder_scheduler()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def isolate_paths(tmp_path, monkeypatch):
    pred_path = str(tmp_path / "predictions.json")
    soul_path = str(tmp_path / "soul_map.json")
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", soul_path)
    Path(pred_path).write_text(
        json.dumps(predictions_store._default_data()),
        encoding="utf-8",
    )
    _stop_prediction_background_jobs()
    monkeypatch.setattr(
        "internal.learning.ledger_heal.heal_daily_pick_ledger",
        lambda *args, **kwargs: {"ok": True, "healed": False, "reason": "test_isolated"},
    )
    orig_load = predictions_store.load_predictions
    orig_save = predictions_store.save_predictions

    def locked_load():
        with _store_lock:
            return orig_load()

    def locked_save(data):
        with _store_lock:
            return orig_save(data)

    monkeypatch.setattr(predictions_store, "load_predictions", locked_load)
    monkeypatch.setattr(predictions_store, "save_predictions", locked_save)
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
    rows = [r for r in data["predictions"] if r.get("netuid") == 29]
    assert len(rows) == 1
    row = rows[0]
    assert row["horizon_type"] == "hour"
    assert row["status"] == "pending"
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
    rows = [
        r for r in predictions_store.load_predictions()["predictions"] if r.get("netuid") == 29
    ]
    assert len(rows) == 1


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
