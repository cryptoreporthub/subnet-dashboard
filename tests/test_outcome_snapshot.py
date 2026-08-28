"""Outcome snapshot + council health score."""

from __future__ import annotations

import internal.learning.council_health_score as health
import internal.learning.outcome_snapshot as snap
import internal.learning.outcome_snapshot_scheduler as sched


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


def test_outcome_snapshot_tracker_is_liveness_compliant(monkeypatch, tmp_path):
    from tests.liveness_conformance import assert_liveness_compliant

    soul = tmp_path / "soul_map.json"
    soul.write_text("{}")
    monkeypatch.setenv("SOUL_MAP_PATH", str(soul))

    def factory():
        return sched.OutcomeSnapshotScheduler().liveness

    assert_liveness_compliant(factory)
