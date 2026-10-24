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


def test_backfill_matches_name_netuid_when_regime_differs(monkeypatch, tmp_path):
    """§16.1: do not leave original blank when regime heuristic disagrees."""
    _setup_paths(monkeypatch, tmp_path)
    pending = scenario_memory.add_scenario(
        "Chutes",
        {"netuid": 64, "direction": "up"},
        outcome=None,
        regime="bull",
    )
    # No scenario_id on prediction — old rows; actual_pct would classify_regime differently
    predictions_store.save_predictions(
        {
            "predictions": [],
            "resolved": [
                {
                    "id": "pred_regime_gap",
                    "name": "Chutes",
                    "netuid": 64,
                    "correct": False,
                    "actual_pct": -0.1,
                    "predicted_pct": 1.0,
                    "status": "resolved",
                }
            ],
            "stats": {"total": 1, "correct": 0, "wrong": 1, "pending": 0},
        }
    )

    result = backfill_scenario_outcomes_from_predictions()
    assert result["updated"] == 1
    assert result["pending_after"] == 0
    snap = scenario_memory.get_memory_snapshot()["scenarios"]
    assert len(snap) == 1  # no duplicate minted
    assert snap[0]["id"] == pending["id"]
    assert snap[0]["outcome"] == "wrong"


def test_backfill_reports_unresolvable_without_matching_prediction(monkeypatch, tmp_path):
    _setup_paths(monkeypatch, tmp_path)
    orphan = scenario_memory.add_scenario(
        "Orphan",
        {"netuid": 99},
        outcome=None,
        regime="neutral",
    )
    predictions_store.save_predictions(
        {
            "predictions": [],
            "resolved": [],
            "stats": {"total": 0, "correct": 0, "wrong": 0, "pending": 0},
        }
    )

    result = backfill_scenario_outcomes_from_predictions()
    assert result["pending_after"] == 1
    assert result["unresolvable_count"] == 1
    assert result["unresolvable"][0]["scenario_id"] == orphan["id"]
    assert result["unresolvable"][0]["reason"] == "no_matching_prediction"

    stats = scenario_outcome_stats()
    assert stats["unresolvable_count"] == 1
    assert stats["outcomes_pending"] == 1


def test_scenario_outcome_stats_reports_resolved_counts(monkeypatch, tmp_path):
    _setup_paths(monkeypatch, tmp_path)
    scenario_memory.add_scenario("A", {"netuid": 1}, outcome="correct")
    scenario_memory.add_scenario("B", {"netuid": 2}, outcome="wrong")

    stats = scenario_outcome_stats()
    assert stats["scenario_count"] == 2
    assert stats["outcomes_resolved"] == 2
    assert stats["outcomes_pending"] == 0
    assert stats["unresolvable_count"] == 0
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


def test_add_scenario_idempotent_by_prediction_id(monkeypatch, tmp_path):
    _setup_paths(monkeypatch, tmp_path)
    first = scenario_memory.add_scenario(
        "Subnet A",
        {"netuid": 1, "direction": "up"},
        outcome=None,
        prediction_id="pred-dedupe-1",
    )
    second = scenario_memory.add_scenario(
        "Subnet A",
        {"netuid": 1, "direction": "up"},
        outcome=None,
        prediction_id="pred-dedupe-1",
    )
    assert first["id"] == second["id"]
    assert len(scenario_memory.get_memory_snapshot()["scenarios"]) == 1


def test_record_outcome_collapses_by_prediction_id(monkeypatch, tmp_path):
    _setup_paths(monkeypatch, tmp_path)
    pending = scenario_memory.add_scenario(
        "Subnet B",
        {"netuid": 2, "direction": "up"},
        outcome=None,
        prediction_id="pred-collapse-1",
    )
    result = scenario_memory.record_outcome(
        name="Subnet B",
        outcome="correct",
        features={"direction": "up"},
        metadata={"prediction_id": "pred-collapse-1", "actual_pct": 2.5},
    )
    assert result["id"] == pending["id"]
    assert result["outcome"] == "correct"
    assert len(scenario_memory.get_memory_snapshot()["scenarios"]) == 1


def _backfill_with_unmatched_predictions(monkeypatch, tmp_path, unmatched):
    tmp_path.mkdir(exist_ok=True)
    _setup_paths(monkeypatch, tmp_path)
    pending = scenario_memory.add_scenario(
        "Chutes", {"netuid": 64, "direction": "up"}, outcome=None, regime="bull"
    )
    resolved = [
        {
            "id": f"pred_{i}",
            "name": f"Other{i}",
            "netuid": 1000 + i,
            "correct": bool(i % 2),
            "status": "resolved",
        }
        for i in range(unmatched)
    ]
    resolved.append(
        {
            "id": "pred_match",
            "name": "Chutes",
            "netuid": 64,
            "correct": True,
            "status": "resolved",
        }
    )
    predictions_store.save_predictions(
        {
            "predictions": [],
            "resolved": resolved,
            "stats": {"total": len(resolved), "correct": 0, "wrong": 0, "pending": 0},
        }
    )
    reads = []
    real_load = scenario_memory._load

    def counting_load(path=None):
        reads.append(1)
        return real_load(path)

    monkeypatch.setattr(scenario_memory, "_load", counting_load)
    result = backfill_scenario_outcomes_from_predictions()
    monkeypatch.setattr(scenario_memory, "_load", real_load)
    return result, len(reads), pending, real_load()["scenarios"][0]


def test_backfill_scenario_memory_reads_do_not_grow_with_prediction_count(monkeypatch, tmp_path):
    small, small_reads, _, _ = _backfill_with_unmatched_predictions(
        monkeypatch, tmp_path / "small", 5
    )
    large, large_reads, pending, stamped = _backfill_with_unmatched_predictions(
        monkeypatch, tmp_path / "large", 400
    )

    assert large["updated"] == small["updated"] == 1
    assert large["pending_after"] == 0
    assert large_reads == small_reads
    assert stamped["id"] == pending["id"]
    assert stamped["outcome"] == "correct"


def test_backfill_stamps_each_pending_scenario_once_in_one_pass(monkeypatch, tmp_path):
    _setup_paths(monkeypatch, tmp_path)
    by_id = scenario_memory.add_scenario("A", {"netuid": 1}, outcome=None, regime="bull")
    by_name_netuid = scenario_memory.add_scenario("B", {"netuid": 2}, outcome=None, regime="bear")
    by_name = scenario_memory.add_scenario("C", {"netuid": 3}, outcome=None, regime="neutral")
    untouched = scenario_memory.add_scenario("D", {"netuid": 4}, outcome=None, regime="bull")
    predictions_store.save_predictions(
        {
            "predictions": [],
            "resolved": [
                {"id": "p1", "name": "A", "netuid": 1, "scenario_id": by_id["id"], "correct": True, "status": "resolved"},
                {"id": "p2", "name": "B", "netuid": 2, "correct": False, "status": "resolved"},
                {"id": "p3", "name": "C", "netuid": 99, "correct": True, "status": "resolved"},
                {"id": "p4", "name": "C", "netuid": 98, "correct": False, "status": "resolved"},
            ],
            "stats": {"total": 4, "correct": 2, "wrong": 2, "pending": 0},
        }
    )

    result = backfill_scenario_outcomes_from_predictions()

    outcomes = {s["id"]: s.get("outcome") for s in scenario_memory.get_memory_snapshot()["scenarios"]}
    assert outcomes[by_id["id"]] == "correct"
    assert outcomes[by_name_netuid["id"]] == "wrong"
    assert outcomes[by_name["id"]] == "correct"
    assert outcomes[untouched["id"]] is None
    assert result["updated"] == 3
    assert result["pending_after"] == 1


def test_backfill_does_not_restamp_a_scenario_that_already_has_the_outcome(monkeypatch, tmp_path):
    _setup_paths(monkeypatch, tmp_path)
    keep = scenario_memory.add_scenario("A", {"netuid": 1}, outcome=None, regime="bull")
    scenario_memory.add_scenario("Pending", {"netuid": 2}, outcome=None, regime="bull")
    predictions_store.save_predictions(
        {
            "predictions": [],
            "resolved": [
                {"id": "p1", "name": "A", "netuid": 1, "scenario_id": keep["id"], "correct": True, "status": "resolved"},
            ],
            "stats": {"total": 1, "correct": 1, "wrong": 0, "pending": 0},
        }
    )
    backfill_scenario_outcomes_from_predictions()
    first = [s for s in scenario_memory.get_memory_snapshot()["scenarios"] if s["id"] == keep["id"]][0]

    again = backfill_scenario_outcomes_from_predictions()

    second = [s for s in scenario_memory.get_memory_snapshot()["scenarios"] if s["id"] == keep["id"]][0]
    assert again["updated"] == 0
    assert second["resolved_at"] == first["resolved_at"]


def test_backfill_keeps_a_scenario_added_while_it_is_matching(monkeypatch, tmp_path):
    from internal.learning import scenario_outcomes

    _setup_paths(monkeypatch, tmp_path)
    scenario_memory.add_scenario("A", {"netuid": 1}, outcome=None, regime="bull")
    scenario_memory.add_scenario("B", {"netuid": 2}, outcome=None, regime="bull")
    predictions_store.save_predictions(
        {
            "predictions": [],
            "resolved": [
                {"id": "p1", "name": "A", "netuid": 1, "correct": True, "status": "resolved"},
                {"id": "p2", "name": "B", "netuid": 2, "correct": False, "status": "resolved"},
            ],
            "stats": {"total": 2, "correct": 1, "wrong": 1, "pending": 0},
        }
    )
    real_stamp = scenario_outcomes._PendingIndex.stamp
    added = []

    def stamp_while_worker_adds(self, pred, label):
        if not added:
            added.append(scenario_memory.add_scenario("Late", {"netuid": 3}, outcome=None, regime="bull"))
        return real_stamp(self, pred, label)

    monkeypatch.setattr(scenario_outcomes._PendingIndex, "stamp", stamp_while_worker_adds)

    result = backfill_scenario_outcomes_from_predictions()

    ids = {s["id"]: s.get("outcome") for s in scenario_memory.get_memory_snapshot()["scenarios"]}
    assert result["updated"] == 2
    assert added[0]["id"] in ids
    assert ids[added[0]["id"]] is None


def test_apply_stamps_keeps_a_scenario_added_by_another_writer_mid_update(monkeypatch, tmp_path):
    import threading

    _setup_paths(monkeypatch, tmp_path)
    target = scenario_memory.add_scenario("A", {"netuid": 1}, outcome=None, regime="bull")
    writer = threading.Thread(
        target=lambda: scenario_memory.add_scenario("Inside", {"netuid": 2}, outcome=None, regime="bull")
    )
    real_load = scenario_memory._load
    started = []

    def load_then_race(path=None):
        data = real_load(path)
        if not started:
            started.append(1)
            writer.start()
            writer.join(timeout=0.5)
        return data

    monkeypatch.setattr(scenario_memory, "_load", load_then_race)

    updated = scenario_memory.apply_stamps([(target["id"], "correct", {})])
    writer.join()
    monkeypatch.setattr(scenario_memory, "_load", real_load)

    assert updated == 1
    stored = {s["name"]: s.get("outcome") for s in real_load()["scenarios"]}
    assert stored == {"A": "correct", "Inside": None}
