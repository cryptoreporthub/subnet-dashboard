"""Phase N2 — scenario-memory outcome wiring."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import internal.council.scenario_memory as scenario_memory
import internal.learning.predictions_store as predictions_store
from internal.learning.prediction_loop import record_pick_prediction
from internal.learning.scenario_outcomes import (
    backfill_scenario_outcomes_from_predictions,
    scenario_outcome_stats,
)
from server import app


@pytest.fixture
def client():
    return TestClient(app)


def _setup_paths(monkeypatch, tmp_path):
    scen = tmp_path / "scenario_memory.json"
    pred = tmp_path / "predictions.json"
    monkeypatch.setattr(scenario_memory, "SCENARIO_MEMORY_PATH", str(scen))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred))
    scen.write_text(json.dumps({"scenarios": [], "regimes": {}, "meta": {}}))
    pred.write_text(
        json.dumps(
            {
                "predictions": [],
                "resolved": [],
                "stats": {"total": 0, "correct": 0, "wrong": 0, "pending": 0},
            }
        )
    )
    return scen, pred


def test_record_pick_prediction_sets_scenario_id(monkeypatch, tmp_path):
    _setup_paths(monkeypatch, tmp_path)
    subnet = {
        "netuid": 19,
        "name": "Inference",
        "price": 1.0,
        "volume": 5000,
        "price_change_24h": 2.0,
        "emission": 2.0,
    }
    pick = {
        "subnet": subnet,
        "score": 72.0,
        "confidence": 0.62,
        "expert_contributions": {"quant": 0.5, "hype": 0.5, "dark_horse": 0.5, "technical": 0.5},
        "scenario_tags": {"regime": "neutral"},
        "signals": {"price_change_24h": 2.0},
    }
    pred = record_pick_prediction(pick, subnet, horizon_type="hour", market_context={"weights": {}})
    assert pred is not None
    assert pred.get("scenario_id")

    snap = scenario_memory.get_memory_snapshot()
    assert snap["scenarios"]
    assert snap["scenarios"][-1]["id"] == pred["scenario_id"]
    assert snap["scenarios"][-1]["outcome"] is None


def test_backfill_stamps_blank_scenarios_from_resolved_predictions(monkeypatch, tmp_path):
    _setup_paths(monkeypatch, tmp_path)
    pending = scenario_memory.add_scenario(
        "Chutes",
        {"netuid": 64, "direction": "up"},
        outcome=None,
        regime="bull",
    )
    predictions_store.save_predictions(
        {
            "predictions": [],
            "resolved": [
                {
                    "id": "pred_test_1",
                    "name": "Chutes",
                    "netuid": 64,
                    "scenario_id": pending["id"],
                    "correct": True,
                    "actual_pct": 4.2,
                    "predicted_pct": 3.0,
                    "status": "resolved",
                }
            ],
            "stats": {"total": 1, "correct": 1, "wrong": 0, "pending": 0},
        }
    )

    result = backfill_scenario_outcomes_from_predictions()
    assert result["updated"] >= 1
    assert result["pending_after"] == 0

    updated = scenario_memory.get_memory_snapshot()["scenarios"][-1]
    assert updated["outcome"] == "correct"
    assert (updated.get("metadata") or {}).get("prediction_id") == "pred_test_1"


def test_scenario_outcome_stats_reports_resolved_counts(monkeypatch, tmp_path):
    _setup_paths(monkeypatch, tmp_path)
    scenario_memory.add_scenario("A", {"netuid": 1}, outcome="correct")
    scenario_memory.add_scenario("B", {"netuid": 2}, outcome="wrong")

    stats = scenario_outcome_stats()
    assert stats["scenario_count"] == 2
    assert stats["outcomes_resolved"] == 2
    assert stats["outcomes_pending"] == 0
    assert stats["last_outcome"] == "wrong"


def test_learning_stats_includes_scenario_memory(client, monkeypatch, tmp_path):
    _setup_paths(monkeypatch, tmp_path)
    scenario_memory.add_scenario("SN1", {"netuid": 1}, outcome="correct")

    resp = client.get("/api/learning/stats")
    assert resp.status_code == 200
    body = resp.json()
    sm = body["data"]["scenario_memory"]
    assert sm["outcomes_resolved"] >= 1
    assert sm["last_outcome"] == "correct"
