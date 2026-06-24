import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from internal.council.learner import LearningLoop


def test_learner_init():
    with tempfile.TemporaryDirectory() as tmpdir:
        sm_path = os.path.join(tmpdir, "soul_map.json")
        out_path = os.path.join(tmpdir, "outcomes.jsonl")
        loop = LearningLoop(soul_map_path=sm_path, outcomes_path=out_path)

        assert loop.soul_map_path == sm_path
        assert loop.outcomes_path == out_path
        assert os.path.exists(sm_path)
        assert os.path.exists(out_path)
        assert loop.soul_map == {"verdicts": [], "expert_weights": {}}
        assert loop.outcomes == []


def test_learner_run_with_mock_registry():
    with tempfile.TemporaryDirectory() as tmpdir:
        sm_path = os.path.join(tmpdir, "soul_map.json")
        out_path = os.path.join(tmpdir, "outcomes.jsonl")

        # Pre-create soul_map so the orchestrator can read it
        with open(sm_path, "w") as f:
            json.dump({"verdicts": [], "expert_weights": {}}, f)

        mock_decisions = [
            {
                "subnet_id": 1,
                "consensus_score": 0.85,
                "recommended_action": "accumulate",
                "expert_breakdown": {},
            },
            {
                "subnet_id": 2,
                "consensus_score": 0.35,
                "recommended_action": "reduce",
                "expert_breakdown": {},
            },
        ]
        mock_result = {"daily_output": {"decisions": mock_decisions}}

        def mock_judge(pick):
            return {
                "timestamp": "2026-01-01T00:00:00",
                "confidence": 0.8,
                "dissent": False,
                "reasoning": "mock",
                "verdict": "aligned",
            }

        with patch(
            "internal.council.orchestrator.Orchestrator"
        ) as mock_orch_cls, patch(
            "internal.council.adversarial_judge.judge_decision", side_effect=mock_judge
        ):
            mock_orch = MagicMock()
            mock_orch.run_daily_rotation.return_value = mock_result
            mock_orch_cls.return_value = mock_orch

            loop = LearningLoop(soul_map_path=sm_path, outcomes_path=out_path)
            summary = loop.run()

        assert os.path.exists(out_path)
        with open(out_path) as f:
            lines = f.readlines()
        assert len(lines) == 2

        assert summary["total_outcomes"] == 2
        assert summary["total_verdicts"] == 0  # verdicts in soul_map from orchestrator path


def test_learner_outcome_comparison():
    with tempfile.TemporaryDirectory() as tmpdir:
        sm_path = os.path.join(tmpdir, "soul_map.json")
        out_path = os.path.join(tmpdir, "outcomes.jsonl")

        # Pre-populate outcomes.jsonl with 2 aligned, 1 divergent
        entries = [
            {"verdict": "aligned", "netuid": 1},
            {"verdict": "aligned", "netuid": 2},
            {"verdict": "divergent", "netuid": 3},
        ]
        with open(out_path, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        loop = LearningLoop(soul_map_path=sm_path, outcomes_path=out_path)
        # Manually set outcomes to match what was loaded
        loop.outcomes = entries

        # aligned (2) > divergent (1), so weights should increase
        loop._compare_outcomes()

        weights = loop.soul_map.get("expert_weights", {})
        assert "QuantExpert" in weights
        # With aligned > divergent, weights should be boosted by 0.02
        assert weights["QuantExpert"] == pytest.approx(1.02, abs=0.001)


def test_learner_api_endpoints():
    from server import app

    app.config["TESTING"] = True
    with app.test_client() as client:
        # GET /api/learning-loop/status
        resp = client.get("/api/learning-loop/status")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert "aligned_pct" in data["data"]
        assert "divergent_pct" in data["data"]
        assert "expert_weights" in data["data"]

        # GET /api/learning-loop/outcomes?limit=10
        resp = client.get("/api/learning-loop/outcomes?limit=10")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert isinstance(data["data"], list)

        # POST /api/learning-loop/run
        resp = client.post("/api/learning-loop/run")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert "total_outcomes" in data["data"]


def test_learner_missing_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        sm_path = os.path.join(tmpdir, "nonexistent", "soul_map.json")
        out_path = os.path.join(tmpdir, "nonexistent", "outcomes.jsonl")

        loop = LearningLoop(soul_map_path=sm_path, outcomes_path=out_path)

        assert os.path.exists(sm_path)
        assert os.path.exists(out_path)
        assert loop.soul_map == {"verdicts": [], "expert_weights": {}}
        assert loop.outcomes == []
        assert loop._compute_aligned_pct() == 0.0
        assert loop._compute_divergent_pct() == 0.0