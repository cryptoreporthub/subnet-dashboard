"""Outcome snapshot + council health score."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

import internal.learning.council_health_score as health
import internal.learning.outcome_snapshot as snap
import internal.learning.outcome_snapshot_scheduler as sched


@pytest.fixture(autouse=True)
def isolate_liveness_persistence(tmp_path, monkeypatch):
    """Point internal.liveness soul-map IO at a per-test JSON file (atomic)."""
    from internal import liveness as _liv_mod

    sm_path = tmp_path / "liveness_soul_map.json"

    def _read():
        try:
            return json.loads(sm_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write(mutator):
        blob = _read() or {}
        mutator(blob)
        fd, tmp = tempfile.mkstemp(dir=str(sm_path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(blob, f)
            os.replace(tmp, sm_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    monkeypatch.setattr(_liv_mod, "write_soul_map", _write)
    monkeypatch.setattr(_liv_mod, "read_soul_map", _read)


def test_council_health_score_watch_at_33pct():
    stats = {"correct": 154, "wrong": 314, "accuracy": 0.33, "total": 471}
    banner = {
        "integrity_gate": {"graded_ok": True, "expired_ok": True, "watchdog_ok": True},
    }
    out = health.compute_council_health(stats, banner)
    assert out["health_score"] == 67
    assert out["escalation"] == "WATCH"
    assert any("33%" in r or "accuracy" in r.lower() for r in out["escalation_reasons"])


def test_evaluate_alerts_ok():
    core = {
        "council_health": {"escalation": "OK", "escalation_reasons": []},
        "loop_health": {"status": "ok"},
    }
    level, reasons = snap._evaluate_alerts(core)
    assert level == "ok"
    assert reasons == []


def test_exit_code_alert():
    assert snap.exit_code_for_level("alert") == 2
    assert snap.exit_code_for_level("warn") == 0


def test_build_snapshot_mocked(monkeypatch):
    monkeypatch.setattr(
        snap,
        "_collect_learning_snapshot",
        lambda: {
            "council_health": {"escalation": "OK", "health_score": 75},
            "loop_health": {"status": "ok"},
        },
    )
    monkeypatch.setattr(snap, "_artifact_refs", lambda: {})
    payload = snap.build_outcome_snapshot()
    assert payload["alert_level"] == "ok"
    assert payload["council_health"]["health_score"] == 75


def test_save_snapshot_writes_latest(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_OUTCOMES_DIR", str(tmp_path))
    path = snap.save_snapshot({"status": "ok", "alert_level": "ok"})
    assert path.endswith(".json")
    assert (tmp_path / "latest.json").is_file()


def test_scheduler_disabled(monkeypatch):
    monkeypatch.setenv("OUTCOME_SNAPSHOT_ENABLED", "off")
    out = sched.start_outcome_snapshot_scheduler()
    assert out["started"] is False


def test_evidence_report_empty():
    from internal.ops.evidence import build_evidence_report

    report = build_evidence_report()
    assert "status" in report
    assert "pick_audit" in report


def test_outcome_snapshot_tracker_is_liveness_compliant():
    from tests.liveness_conformance import assert_liveness_compliant

    def factory():
        return sched.OutcomeSnapshotScheduler().liveness

    assert_liveness_compliant(factory)
