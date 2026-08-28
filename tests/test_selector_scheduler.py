"""Selector rotation scheduler — LivenessTracker adoption (issue #1081)."""

from __future__ import annotations

from unittest.mock import patch

from internal.council import selector_scheduler as sched
from tests.liveness_conformance import assert_liveness_compliant


def _make_scheduler(**kwargs):
    return sched.SelectorScheduler(refresh_minutes=kwargs.get("refresh_minutes", 60))


def test_tracker_is_liveness_compliant():
    assert_liveness_compliant(lambda: _make_scheduler().liveness)


def test_state_last_run_ok_derived_from_tracker():
    scheduler = _make_scheduler()
    assert scheduler.state()["last_run_ok"] is not True

    scheduler.liveness.record_success(evidence={"decisions": 1, "op": "daily_rotation"})
    assert scheduler.state()["last_run_ok"] is True


def test_success_tick_records_tracker_success():
    scheduler = _make_scheduler()
    scheduler._active = True

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
    assert scheduler.state()["last_run_ok"] is True
    schedule.assert_called_once()


def test_failure_tick_records_tracker_failure():
    scheduler = _make_scheduler()
    scheduler._active = True

    with patch("internal.council.orchestrator.Orchestrator") as orch_cls:
        orch_cls.return_value.run_daily_rotation.side_effect = RuntimeError("boom")
        with patch.object(scheduler, "_schedule") as schedule:
            result = scheduler._tick()

    assert result["ok"] is False
    assert "boom" in result["error"]
    assert scheduler.liveness.snapshot()["consecutive_failures"] >= 1
    assert scheduler.state()["last_run_ok"] is not True
    schedule.assert_called_once()


def test_stopped_state_uses_registry_liveness():
    state = sched.get_selector_scheduler_state()
    assert state["running"] is False
    assert state.get("last_run_ok") is not True
