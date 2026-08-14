from fastapi.testclient import TestClient

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


def test_learning_stats_exposes_shared_loop_state():
    payload = TestClient(app).get("/api/learning/stats").json()["data"]

    assert isinstance(payload["pump_desk_trust"], dict)
    assert set(("graded", "pending", "retryable")).issubset(payload["resolver_state"])
    assert set(("graded", "pending", "retryable")).issubset(payload["loop_learned"])


def test_mindmap_graph_exposes_learning_state():
    payload = TestClient(app).get("/api/mindmap/graph").json()

    assert isinstance(payload["learning_state"], dict)
    assert "resolver" in payload["learning_state"]
    assert "loop_learned" in payload["learning_state"]
