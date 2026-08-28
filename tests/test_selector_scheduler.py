"""Selector rotation scheduler — LivenessTracker adoption (issue #1081)."""

from __future__ import annotations

from unittest.mock import patch

from internal.council import selector_scheduler as sched
from tests.liveness_conformance import assert_liveness_compliant


def _make_scheduler(**kwargs):
    return sched.SelectorScheduler(refresh_minutes=kwargs.get("refresh_minutes", 60))


def test_tracker_is_liveness_compliant(monkeypatch, tmp_path):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}")
    monkeypatch.setenv("SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))

    def factory():
        return _make_scheduler().liveness

    assert_liveness_compliant(factory)


def test_state_exposes_liveness_without_last_run_ok():
    scheduler = _make_scheduler()
    state = scheduler.state()
    assert "last_run_ok" not in state
    assert state["liveness"]["status"] != "ok"

    scheduler.liveness.record_success(evidence={"decisions": 1, "op": "daily_rotation"})
    state = scheduler.state()
    assert "last_run_ok" not in state
    assert state["liveness"]["status"] == "ok"


def test_running_derived_from_tracker_lifecycle(monkeypatch, tmp_path):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}")
    monkeypatch.setenv("SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    scheduler = _make_scheduler()
    assert scheduler.state()["running"] is False
    scheduler.liveness.start()
    assert scheduler.state()["running"] is True


def test_success_tick_records_tracker_success():
    sched.stop_selector_scheduler()
    scheduler = _make_scheduler()
    with sched._lock:
        sched._scheduler = scheduler
    scheduler.liveness.start()

    rotation = {
        "daily_output": {"decisions": [{"subnet_id": 1}]},
        "feedback_loop": {},
    }

    with patch("internal.council.orchestrator.Orchestrator") as orch_cls:
        orch_cls.return_value.run_daily_rotation.return_value = rotation
        with patch.object(scheduler, "_schedule") as schedule:
            with patch(
                "internal.learning.trail_bus.emit_disposition_shift",
            ):
                result = scheduler._tick()

    assert result["ok"] is True
    assert result["decisions"] == 1
    assert scheduler.liveness.snapshot()["status"] == "ok"
    assert "last_run_ok" not in scheduler.state()
    schedule.assert_called_once()
    sched.stop_selector_scheduler()


def test_failure_tick_records_tracker_failure():
    sched.stop_selector_scheduler()
    scheduler = _make_scheduler()
    with sched._lock:
        sched._scheduler = scheduler
    scheduler.liveness.start()

    with patch("internal.council.orchestrator.Orchestrator") as orch_cls:
        orch_cls.return_value.run_daily_rotation.side_effect = RuntimeError("boom")
        with patch.object(scheduler, "_schedule") as schedule:
            result = scheduler._tick()

    assert result["ok"] is False
    assert "boom" in result["error"]
    assert scheduler.liveness.snapshot()["consecutive_failures"] >= 1
    assert "last_run_ok" not in scheduler.state()
    schedule.assert_called_once()
    sched.stop_selector_scheduler()


def test_stopped_state_uses_registry_liveness():
    sched.stop_selector_scheduler()
    state = sched.get_selector_scheduler_state()
    assert state["running"] is False
    assert "last_run_ok" not in state
    assert "liveness" in state
