"""Slice 7b weight audit + learning stats timeout guards."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from internal.learning import routes as learning_routes
from internal.ops.evidence import build_evidence_report
from server import app


def test_evidence_includes_weight_audit():
    report = build_evidence_report()
    assert "weight_audit" in report
    audit = report["weight_audit"]
    assert audit.get("read_only") is True
    assert "expert_weights" in audit
    assert "judge_weights" in audit
    assert audit.get("combined_weights_frozen") is True
    assert isinstance(audit.get("known_gaps"), list)


def test_weight_audit_online_path_no_archive_replay():
    from internal.learning.weight_audit import build_weight_audit_report

    audit = build_weight_audit_report()
    assert audit["online_path"].get("archive_replay_in_prod") is False


def test_api_learning_stats_timeout_returns_degraded(monkeypatch):
    learning_routes._learning_snapshot_cache["data"] = None
    learning_routes._learning_snapshot_cache["at"] = 0.0

    async def _boom(*_a, **_k):
        raise TimeoutError()

    monkeypatch.setattr(learning_routes, "_to_thread_timeout", _boom)

    resp = TestClient(app).get("/api/learning/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "degraded"
    assert body.get("meta", {}).get("source") == "timeout"
    assert body["data"]["trust_banner"]["ready"] is False


def test_api_learning_stats_timeout_returns_stale_cache(monkeypatch):
    stale_snap = {
        "engine_stats": {
            "expert_weights": {"quant": 1.0},
            "total_records": 5,
            "accuracy": 0.6,
            "pending": 0,
            "last_updated": "2026-08-05T00:00:00Z",
            "resolved": 5,
        },
        "resolver_stats": {
            "correct": 3,
            "wrong": 2,
            "total": 5,
            "accuracy": 0.6,
            "expired": 0,
            "duplicate": 0,
            "pending": 0,
        },
        "watchdog": {},
        "trust_banner": {
            "ready": True,
            "graded": 5,
            "accuracy": 0.6,
            "expired_rate": 0.0,
            "integrity_gate": {},
        },
        "judge_weights": {},
        "judge_last5": {},
        "council_last5": [],
        "scenario": {},
        "predictions_data": {"predictions": [], "resolved": []},
    }
    learning_routes._learning_snapshot_cache["data"] = stale_snap
    learning_routes._learning_snapshot_cache["at"] = time.time() - 999
    monkeypatch.setattr(learning_routes, "LEARNING_STATS_TIMEOUT", 0.05)

    def _slow():
        time.sleep(2)
        return stale_snap

    monkeypatch.setattr(learning_routes, "_learning_snapshot", _slow)

    resp = TestClient(app).get("/api/learning/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "degraded"
    assert body["data"]["graded"] == 5
