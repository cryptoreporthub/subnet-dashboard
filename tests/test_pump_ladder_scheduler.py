"""Pump ladder scheduler - tracker health + persisted run meta."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from tests.liveness_conformance import assert_liveness_compliant


def _make_scheduler():
    from internal.pump.scheduler import PumpLadderScheduler

    return PumpLadderScheduler(refresh_minutes=20)


def test_heavy_job_skip_records_tracker_skip():
    sched = _make_scheduler()
    sched._active = True

    @contextmanager
    def _busy(_name: str):
        yield False

    with patch("internal.heavy_job_gate.heavy_job_slot", _busy):
        with patch("internal.pump.scheduler._persist_scheduler_meta") as persist:
            with patch.object(sched, "_schedule_next") as schedule_next:
                result = sched._tick()

    assert result.get("skipped") == "heavy_job_busy"
    assert sched._last_tick_at is not None
    assert sched.liveness.snapshot()["consecutive_skips"] >= 1
    assert sched.state()["last_run_ok"] is not True
    persist.assert_called_once()
    schedule_next.assert_called_once_with(result)


def test_fast_retry_on_shutdown_error():
    from internal.pump.scheduler import _needs_fast_retry

    assert _needs_fast_retry({"ok": False, "error": "cannot schedule new futures after interpreter shutdown"})
    assert not _needs_fast_retry({"ok": True})
    assert not _needs_fast_retry({"ok": False, "error": "disk full"})


def test_schedule_next_uses_retry_minutes_on_transient_failure():
    sched = _make_scheduler()
    sched._active = True
    with patch.object(sched, "_schedule") as schedule:
        sched._schedule_next({"ok": False, "error": "scan_in_progress"})
    schedule.assert_called_once_with(3)


def test_get_scheduler_state_falls_back_to_persisted_meta(tmp_path, monkeypatch):
    ladder = tmp_path / "pump_ladder.json"
    ladder.write_text(
        '{"version":"1.0","subnets":{},"meta":{"last_scan_at":"2026-07-30T01:00:00Z",'
        '"phase_counts":{"DORMANT":1},"scheduler_last_run_at":"2026-07-30T02:00:00Z",'
        '"scheduler_last_run_ok":true}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("internal.pump.constants.STATE_PATH", str(ladder))

    from internal.pump.scheduler import get_pump_ladder_scheduler_state

    state = get_pump_ladder_scheduler_state()
    assert state["last_run_at"] == "2026-07-30T02:00:00Z"
    # last_run_ok is NEVER backfilled from persisted state (issue #1029)
    assert state.get("last_run_ok") is not True
    assert "liveness" not in state


def test_get_scheduler_state_falls_back_to_last_scan_at(tmp_path, monkeypatch):
    ladder = tmp_path / "pump_ladder.json"
    ladder.write_text(
        '{"version":"1.0","subnets":{},"meta":{"last_scan_at":"2026-07-30T03:00:00Z",'
        '"phase_counts":{"STIRRING":2}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("internal.pump.constants.STATE_PATH", str(ladder))

    from internal.pump.scheduler import get_pump_ladder_scheduler_state

    state = get_pump_ladder_scheduler_state()
    assert state["last_run_at"] == "2026-07-30T03:00:00Z"
    assert state["last_result"]["phase_counts"]["STIRRING"] == 2


def test_record_ladder_scan_run_persists_meta(tmp_path, monkeypatch):
    ladder = tmp_path / "pump_ladder.json"
    ladder.write_text('{"version":"1.0","subnets":{},"meta":{}}', encoding="utf-8")
    monkeypatch.setattr("internal.pump.constants.STATE_PATH", str(ladder))

    from internal.pump.scheduler import record_ladder_scan_run

    record_ladder_scan_run(
        {
            "ok": True,
            "run_at": "2026-07-30T04:00:00Z",
            "scanned": 3,
            "phase_counts": {"STIRRING": 2},
        }
    )

    from internal.file_utils import safe_read_json

    meta = safe_read_json(str(ladder), default={}).get("meta") or {}
    assert meta.get("scheduler_last_run_at") == "2026-07-30T04:00:00Z"
    assert meta.get("scheduler_last_result", {}).get("phase_counts") == {"STIRRING": 2}
    # ok is never persisted as a scalar health signal (issue #1029)
    assert "scheduler_last_run_ok" not in meta


def test_tracker_is_liveness_compliant():
    sched = _make_scheduler()
    assert_liveness_compliant(lambda: sched.liveness)