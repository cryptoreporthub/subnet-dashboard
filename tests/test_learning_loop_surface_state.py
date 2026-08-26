from fastapi.testclient import TestClient

from internal.learning import routes as learning_routes
from internal.learning.trust_stats import build_trust_banner
from server import app


def test_trust_banner_exposes_sample_and_gate_reason():
    banner = build_trust_banner({"correct": 2, "wrong": 1, "pending": 4}, min_graded=10)

    assert banner["sample"] == {
        "graded": 3,
        "correct": 2,
        "wrong": 1,
        "pending": 4,
        "expired": 0,
        "duplicate": 0,
        "total": 7,
        "minimum": 10,
    }
    assert banner["gate_reason"] == "insufficient_graded_sample"


def test_learning_stats_exposes_shared_loop_state(monkeypatch):
    learning_routes._learning_snapshot_cache["data"] = None
    learning_routes._learning_snapshot_cache["at"] = 0.0
    seeded = [
        {
            "event_type": "weight_change",
            "judge": "hype",
            "evidence": {"delta": -0.03, "dial": "hype", "before": 1.0, "after": 0.97},
        },
        {
            "event_type": "weight_change",
            "judge": "impact_strength",
            "evidence": {
                "delta": 0.02,
                "dial": "impact_strength",
                "before": 1.0,
                "after": 1.02,
            },
        },
    ]
    monkeypatch.setattr(
        "internal.learning.weight_deltas.collect_weight_trail_events",
        lambda limit=500: seeded,
    )

    payload = TestClient(app).get("/api/learning/stats").json()["data"]

    assert isinstance(payload["pump_desk_trust"], dict)
    assert isinstance(payload["pump_evaluation"], dict)
    assert "adaptation_gate" in payload["pump_evaluation"]
    assert set(("graded", "pending", "retryable")).issubset(payload["resolver_state"])
    assert set(("graded", "pending", "retryable")).issubset(payload["loop_learned"])
    assert isinstance(payload["loop_learned"]["weight_updates"], int)
    assert payload["loop_learned"]["weight_updates"] > 0
    assert "weight_updates_expert" not in payload["loop_learned"]
    assert "weight_updates_judge" not in payload["loop_learned"]
    assert "weight_updates_scope" not in payload["loop_learned"]


def test_mindmap_graph_exposes_learning_state():
    payload = TestClient(app).get("/api/mindmap/graph").json()

    assert isinstance(payload["learning_state"], dict)
    assert "resolver" in payload["learning_state"]
    assert "loop_learned" in payload["learning_state"]
    assert "pump_evaluation" in payload["learning_state"]


def test_home_ssr_exposes_non_empty_learning_state_labels():
    html = TestClient(app).get("/").text

    assert "evaluation" in html
    assert "pending" in html
    assert "retryable" in html
