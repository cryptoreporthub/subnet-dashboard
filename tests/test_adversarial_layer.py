"""
Closed-loop end-to-end tests for the Outcome-Driven Adversarial Intelligence Layer.

These tests exercise the AdversarialJudge, the AdversarialScheduler, and the
SimiVision API integration using mocked time and deterministic outcomes. All
public data shapes are validated against JSON schemas.
"""

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone

import pytest
from freezegun import freeze_time
from jsonschema import validate

from internal.council.judge.adversarial import AdversarialJudge
from internal.scheduler import AdversarialScheduler
from server import app


# ---------------------------------------------------------------------------
# JSON schemas
# ---------------------------------------------------------------------------
VERDICT_SCHEMA = {
    "type": "object",
    "required": [
        "subnet_id",
        "score",
        "confidence",
        "action",
        "note",
        "outcome_label",
        "expert_contributions",
        "timestamp",
    ],
    "properties": {
        "subnet_id": {"type": ["integer", "null"]},
        "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "action": {"type": "string"},
        "note": {"type": "string"},
        "outcome_label": {"type": "string"},
        "expert_contributions": {
            "type": "object",
            "minProperties": 3,
        },
        "timestamp": {"type": "string"},
    },
}

EXPERT_CONTRIBUTION_SCHEMA = {
    "type": "object",
    "required": ["score", "weight", "accuracy"],
    "properties": {
        "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "weight": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "accuracy": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
}

SCHEDULER_STATE_SCHEMA = {
    "type": "object",
    "required": [
        "running",
        "refresh_minutes",
        "backoff_minutes",
        "consecutive_failures",
        "last_run_at",
        "last_run_ok",
        "last_run_error",
        "next_run_at",
    ],
    "properties": {
        "running": {"type": "boolean"},
        "refresh_minutes": {"type": "integer", "minimum": 1},
        "backoff_minutes": {"type": "integer", "minimum": 1},
        "consecutive_failures": {"type": "integer", "minimum": 0},
        "last_run_at": {"type": ["string", "null"]},
        "last_run_ok": {"type": ["boolean", "null"]},
        "last_run_error": {"type": ["string", "null"]},
        "next_run_at": {"type": ["number", "null"]},
    },
}

LEARNING_TRAIL_ENTRY_SCHEMA = {
    "type": "object",
    "required": [
        "timestamp",
        "subnet_id",
        "action",
        "outcome_label",
        "score",
        "confidence",
        "note",
    ],
    "properties": {
        "timestamp": {"type": "string"},
        "subnet_id": {"type": ["integer", "null"]},
        "action": {"type": "string"},
        "outcome_label": {"type": "string"},
        "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "note": {"type": "string"},
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def tmp_soul_map(tmp_path):
    return str(tmp_path / "soul_map.json")


@pytest.fixture
def tmp_registry(tmp_path):
    path = tmp_path / "registry.json"
    registry = {
        "1": {
            "name": "Alpha",
            "emission": 1.5,
            "social_mentions": 500,
            "is_overvalued": False,
            "status": "active",
            "staking_data": {"apy": 0.12, "total_stake": 1_000_000},
        },
        "2": {
            "name": "Beta",
            "emission": 0.3,
            "social_mentions": 50,
            "is_overvalued": True,
            "status": "active",
            "staking_data": {"apy": 0.08, "total_stake": 500_000},
        },
        "3": {
            "name": "Gamma",
            "emission": 0.1,
            "social_mentions": 10,
            "is_overvalued": False,
            "status": "deprecated",
            "staking_data": {"apy": 0.05, "total_stake": 100_000},
        },
    }
    path.write_text(json.dumps(registry))
    return str(path)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ---------------------------------------------------------------------------
# AdversarialJudge unit tests
# ---------------------------------------------------------------------------
def test_judge_validates_accumulate(tmp_soul_map):
    judge = AdversarialJudge(persistence_path=tmp_soul_map, persist=True)
    decision = {
        "subnet_id": 1,
        "recommended_action": "accumulate",
        "expert_breakdown": {
            "quant": {"score": 0.9},
            "hype": {"score": 0.8},
            "contrarian": {"score": 0.7},
        },
    }
    outcome = {
        "status": "active",
        "emission": 1.5,
        "social_mentions": 500,
        "is_overvalued": False,
    }
    verdict = judge.judge_decision(decision, outcome)

    validate(instance=verdict, schema=VERDICT_SCHEMA)
    for expert in verdict["expert_contributions"].values():
        validate(instance=expert, schema=EXPERT_CONTRIBUTION_SCHEMA)

    assert verdict["score"] == 1.0
    assert verdict["outcome_label"] == "validated"
    assert verdict["action"] == "accumulate"


def test_judge_contradicts_reduce_against_momentum(tmp_soul_map):
    judge = AdversarialJudge(persistence_path=tmp_soul_map, persist=True)
    decision = {
        "subnet_id": 2,
        "recommended_action": "reduce",
        "expert_breakdown": {
            "quant": {"score": 0.1},
            "hype": {"score": 0.2},
            "contrarian": {"score": 0.9},
        },
    }
    outcome = {
        "status": "active",
        "emission": 2.0,
        "social_mentions": 2000,
        "is_overvalued": False,
    }
    verdict = judge.judge_decision(decision, outcome)
    validate(instance=verdict, schema=VERDICT_SCHEMA)

    assert verdict["score"] == 0.0
    assert verdict["outcome_label"] == "contradicted"


def test_judge_neutral_hold(tmp_soul_map):
    judge = AdversarialJudge(persistence_path=tmp_soul_map, persist=True)
    verdict = judge.judge_decision(
        {"recommended_action": "hold"},
        {"status": "active", "emission": 0.8, "social_mentions": 50, "is_overvalued": False},
    )
    validate(instance=verdict, schema=VERDICT_SCHEMA)
    assert verdict["score"] == 0.5
    assert verdict["outcome_label"] == "neutral"


def test_judge_persists_and_reloads_state(tmp_soul_map):
    judge = AdversarialJudge(persistence_path=tmp_soul_map, persist=True)
    judge.judge_decision(
        {"subnet_id": 1, "recommended_action": "accumulate"},
        {"status": "active", "emission": 1.5, "social_mentions": 500, "is_overvalued": False},
    )

    reloaded = AdversarialJudge(persistence_path=tmp_soul_map, persist=False)
    assert len(reloaded.get_verdicts()) == 1
    assert set(reloaded.get_council_weights().keys()) == {"quant", "hype", "contrarian"}
    assert set(reloaded.get_expert_track_records().keys()) == {"quant", "hype", "contrarian"}
    assert len(reloaded.get_learning_trail()) == 1


def test_judge_no_persistence_by_default(tmp_soul_map):
    judge = AdversarialJudge(persistence_path=tmp_soul_map)
    judge.judge_decision(
        {"subnet_id": 1, "recommended_action": "accumulate"},
        {"status": "active", "emission": 1.5, "social_mentions": 500, "is_overvalued": False},
    )
    assert not os.path.exists(tmp_soul_map)


def test_judge_weight_convergence(tmp_soul_map):
    """Repeatedly accurate experts should gain weight; inaccurate ones should lose it."""
    judge = AdversarialJudge(persistence_path=tmp_soul_map, persist=True)

    # quant always predicts the outcome perfectly (score 1.0); contrarian is wrong.
    for _ in range(20):
        judge.judge_decision(
            {
                "subnet_id": 1,
                "recommended_action": "accumulate",
                "expert_breakdown": {
                    "quant": {"score": 1.0},
                    "hype": {"score": 0.5},
                    "contrarian": {"score": 0.0},
                },
            },
            {"status": "active", "emission": 1.5, "social_mentions": 500, "is_overvalued": False},
        )

    weights = judge.get_council_weights()
    records = judge.get_expert_track_records()
    assert weights["quant"] > weights["contrarian"]
    assert records["quant"]["accuracy"] > records["contrarian"]["accuracy"]
    assert sum(weights.values()) == pytest.approx(1.0, abs=0.01)


def test_judge_learning_trail_bound(tmp_soul_map):
    judge = AdversarialJudge(persistence_path=tmp_soul_map, persist=True)
    for i in range(10):
        judge.judge_decision(
            {"subnet_id": i, "recommended_action": "hold"},
            {"status": "active", "emission": 0.5, "social_mentions": 50, "is_overvalued": False},
        )
    trail = judge.get_learning_trail(limit=5)
    assert len(trail) == 5
    for entry in trail:
        validate(instance=entry, schema=LEARNING_TRAIL_ENTRY_SCHEMA)


# ---------------------------------------------------------------------------
# Scheduler tests with mocked time
# ---------------------------------------------------------------------------
def test_scheduler_run_once(tmp_soul_map, tmp_registry):
    scheduler = AdversarialScheduler(
        refresh_minutes=1,
        max_backoff_minutes=4,
        soul_map_path=tmp_soul_map,
        registry_path=tmp_registry,
    )
    result = scheduler.run_once()

    assert result["ok"] is True
    assert result["decisions_judged"] == 3
    assert len(result["verdicts"]) == 3
    for verdict in result["verdicts"]:
        validate(instance=verdict, schema=VERDICT_SCHEMA)

    state = scheduler.state()
    validate(instance=state, schema=SCHEDULER_STATE_SCHEMA)
    assert state["last_run_ok"] is True
    assert state["consecutive_failures"] == 0


def test_scheduler_failure_backoff(tmp_soul_map, tmp_registry):
    scheduler = AdversarialScheduler(
        refresh_minutes=1,
        max_backoff_minutes=8,
        soul_map_path=tmp_soul_map,
        registry_path="/nonexistent/registry.json",
    )
    result = scheduler.run_once()
    assert result["ok"] is False
    assert "registry is empty or missing" in result["error"]

    state = scheduler.state()
    assert state["last_run_ok"] is False
    assert state["consecutive_failures"] == 1
    assert state["backoff_minutes"] == 2

    scheduler.run_once()
    assert scheduler.state()["consecutive_failures"] == 2
    assert scheduler.state()["backoff_minutes"] == 4


def test_scheduler_persists_cycle_summary(tmp_soul_map, tmp_registry):
    scheduler = AdversarialScheduler(
        refresh_minutes=1,
        max_backoff_minutes=4,
        soul_map_path=tmp_soul_map,
        registry_path=tmp_registry,
    )
    scheduler.run_once()

    with open(tmp_soul_map, "r") as f:
        data = json.load(f)

    summary = data["adversarial_scheduler"]["last_cycle"]
    assert summary["verdict_count"] == 3
    assert 0.0 <= summary["mean_score"] <= 1.0
    assert 0.0 <= summary["mean_confidence"] <= 1.0
    assert set(summary["council_weights"].keys()) == {"quant", "hype", "contrarian"}


@freeze_time("2026-06-19T12:00:00+00:00")
def test_scheduler_start_stop_and_next_run(tmp_soul_map, tmp_registry):
    scheduler = AdversarialScheduler(
        refresh_minutes=5,
        max_backoff_minutes=60,
        soul_map_path=tmp_soul_map,
        registry_path=tmp_registry,
    )
    start_result = scheduler.start(immediate=False)
    assert start_result["started"] is True
    assert start_result["refresh_minutes"] == 5

    state = scheduler.state()
    assert state["running"] is True
    assert state["next_run_at"] is not None

    # next_run_at is a Unix timestamp 5 minutes in the future.
    expected_next = datetime(2026, 6, 19, 12, 5, 0, tzinfo=timezone.utc).timestamp()
    assert state["next_run_at"] == pytest.approx(expected_next, abs=1.0)

    stop_result = scheduler.stop()
    assert stop_result["stopped"] is True
    assert scheduler.state()["running"] is False
    assert scheduler.state()["next_run_at"] is None


def test_scheduler_idempotent_start(tmp_soul_map, tmp_registry):
    scheduler = AdversarialScheduler(
        refresh_minutes=1,
        max_backoff_minutes=4,
        soul_map_path=tmp_soul_map,
        registry_path=tmp_registry,
    )
    assert scheduler.start()["started"] is True
    assert scheduler.start()["started"] is False
    scheduler.stop()


# ---------------------------------------------------------------------------
# End-to-end API tests
# ---------------------------------------------------------------------------
def test_api_learning_trail_shape(client):
    response = client.get("/api/simivision/learning-trail")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "success"
    assert "learning_trail" in data["data"]
    assert "council_weights" in data["data"]
    assert "expert_track_records" in data["data"]

    weights = data["data"]["council_weights"]
    assert set(weights.keys()) >= {"quant", "hype", "contrarian"}
    assert sum(weights.values()) == pytest.approx(1.0, abs=0.01)


def test_api_scheduler_state_shape(client):
    response = client.get("/api/simivision/scheduler")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "success"
    validate(instance=data["data"], schema=SCHEDULER_STATE_SCHEMA)


def test_api_trace_includes_adversarial_fields(client):
    response = client.get("/api/simivision/1/trace")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "success"

    trace = data["trace"]
    assert "council_weights" in trace
    assert "expert_track_records" in trace
    assert "learning_trail" in trace
    assert set(trace["council_weights"].keys()) >= {"quant", "hype", "contrarian"}
    assert isinstance(trace["learning_trail"], list)


# ---------------------------------------------------------------------------
# Closed-loop integration test with mocked time
# ---------------------------------------------------------------------------
def test_closed_loop_learning_with_mocked_time(tmp_soul_map, tmp_registry):
    """
    Simulate two scheduler cycles separated by an hour. The second cycle
    observes changed outcomes and the judge's learning trail should grow.
    """
    with freeze_time("2026-06-19T10:00:00+00:00") as frozen_time:
        scheduler = AdversarialScheduler(
            refresh_minutes=60,
            max_backoff_minutes=240,
            soul_map_path=tmp_soul_map,
            registry_path=tmp_registry,
        )

        # First cycle: active, strong emission -> accumulate validated.
        result_1 = scheduler.run_once()
        assert result_1["ok"] is True
        assert result_1["decisions_judged"] == 3

        first_labels = {v["subnet_id"]: v["outcome_label"] for v in result_1["verdicts"]}

        # Mutate registry to flip subnet 1 into an overvalued, at-risk state.
        with open(tmp_registry, "r") as f:
            registry = json.load(f)
        registry["1"]["is_overvalued"] = True
        registry["1"]["status"] = "at-risk"
        registry["1"]["emission"] = 0.2
        with open(tmp_registry, "w") as f:
            json.dump(registry, f)

        frozen_time.tick(delta=3600)
        result_2 = scheduler.run_once()
        assert result_2["ok"] is True

        second_labels = {v["subnet_id"]: v["outcome_label"] for v in result_2["verdicts"]}

    judge = AdversarialJudge(persistence_path=tmp_soul_map, persist=False)
    trail = judge.get_learning_trail()
    assert len(trail) >= 6  # 3 subnets x 2 cycles

    # The verdict for subnet 1 should have changed after the outcome flipped.
    assert first_labels[1] != second_labels[1]

    # Weights should still be a valid probability distribution.
    weights = judge.get_council_weights()
    assert sum(weights.values()) == pytest.approx(1.0, abs=0.01)
    assert all(w >= 0.15 for w in weights.values())
