import json
import os
import pytest
from server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


REQUIRED_LEARNING_TRAIL_FIELDS = {"experts", "verdicts", "refresh_minutes"}
REQUIRED_EXPERT_FIELDS = {"name", "weight", "track_record", "confidence", "last_verdict"}
REQUIRED_TRACK_RECORD_FIELDS = {"correct", "total", "accuracy"}
REQUIRED_VERDICT_FIELDS = {"time", "subnet_uid", "prediction", "actual_outcome", "expert_verdicts", "confident"}


def _numeric(value):
    return isinstance(value, (int, float))


def test_api_learning_trail_schema(client):
    """GET /api/learning-trail returns the required schema."""
    response = client.get("/api/learning-trail")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "success"
    assert "data" in data
    payload = data["data"]
    assert REQUIRED_LEARNING_TRAIL_FIELDS.issubset(payload.keys())
    assert isinstance(payload["experts"], list)
    assert isinstance(payload["verdicts"], list)
    assert isinstance(payload["refresh_minutes"], int)

    for expert in payload["experts"]:
        assert REQUIRED_EXPERT_FIELDS.issubset(expert.keys())
        assert isinstance(expert["name"], str)
        assert isinstance(expert["weight"], (int, float))
        assert 0.0 <= expert["weight"] <= 1.0
        assert isinstance(expert["confidence"], (int, float))
        assert 0.0 <= expert["confidence"] <= 1.0
        tr = expert["track_record"]
        assert REQUIRED_TRACK_RECORD_FIELDS.issubset(tr.keys())
        assert _numeric(tr["correct"])
        assert _numeric(tr["total"])
        assert _numeric(tr["accuracy"])
        assert 0.0 <= tr["accuracy"] <= 1.0

    for verdict in payload["verdicts"]:
        assert REQUIRED_VERDICT_FIELDS.issubset(verdict.keys())
        assert isinstance(verdict["time"], str)
        assert isinstance(verdict["subnet_uid"], int)
        assert isinstance(verdict["prediction"], str)
        assert isinstance(verdict["actual_outcome"], str)
        assert isinstance(verdict["expert_verdicts"], list)
        assert isinstance(verdict["confident"], bool)


def test_api_learning_trail_closed_loop_outcome_update(client, tmp_path):
    """A verdict written to data/verdicts.jsonl appears in the learning trail."""
    import internal.council.signals.poller as poller

    verdict = {
        "timestamp": "2099-01-01T00:00:00Z",
        "subnet_id": 42,
        "action": "bullish",
        "outcome_label": "bullish",
        "expert_contributions": {
            "quant": {"score": 0.8, "verdict": "bullish"},
            "hype": {"score": 0.6, "verdict": "bullish"},
        },
        "confidence": 0.75,
    }

    original_path = poller.VERDICTS_JSONL_PATH
    try:
        test_jsonl = tmp_path / "verdicts.jsonl"
        test_jsonl.write_text(json.dumps(verdict) + "\n")
        poller.VERDICTS_JSONL_PATH = str(test_jsonl)

        response = client.get("/api/learning-trail")
        assert response.status_code == 200
        data = json.loads(response.data)["data"]
        assert any(v["subnet_uid"] == 42 for v in data["verdicts"])
        matched = next(v for v in data["verdicts"] if v["subnet_uid"] == 42)
        assert matched["prediction"] == "bullish"
        assert matched["actual_outcome"] == "bullish"
        assert matched["confident"] is True
        assert len(matched["expert_verdicts"]) == 3
    finally:
        poller.VERDICTS_JSONL_PATH = original_path


def test_learning_trail_panel_renders(client):
    """The homepage includes the Learning Trail panel markup and CSS link."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.data.decode()
    assert 'id="learning-trail"' in html
    assert 'id="learning-trail-experts"' in html
    assert 'id="learning-trail-verdicts"' in html
    assert "simivision.css" in html
    assert "loadLearningTrail" in html


def test_pathfinder_weighted_consensus_uses_council_weights():
    """PathfinderWorker recomputes consensus using learned council weights."""
    from internal.council.signals.pathfinder import PathfinderWorker

    worker = PathfinderWorker()
    decision = {
        "expert_breakdown": {
            "quant": {"score": 0.9, "confidence": 0.8},
            "hype": {"score": 0.2, "confidence": 0.6},
            "contrarian": {"score": 0.5, "confidence": 0.4},
        },
        "brain": {"action": "hold", "target_weight": 0.5, "agreement": 0.5},
    }
    worker._weights = {"quant": 0.5, "hype": 0.3, "contrarian": 0.2}
    adjusted = worker.apply_weights(decision)
    assert "brain" in adjusted
    assert "consensus_score" in adjusted
    assert isinstance(adjusted["consensus_score"], (int, float))
    expected = round(0.9 * 0.5 + 0.2 * 0.3 + 0.5 * 0.2, 4)
    assert adjusted["consensus_score"] == expected


def test_engine_builds_signals_with_pathfinder_weights():
    """The SimiVision engine builds 128 signals after applying pathfinder weights."""
    from internal.simivision.engine import SimiVisionEngine

    engine = SimiVisionEngine()
    signals = engine.build_signals()
    assert isinstance(signals, list)
    assert len(signals) == 128
