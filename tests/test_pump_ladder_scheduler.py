"""Pump ladder scheduler — persisted run meta + skip-path recording."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest


def test_heavy_job_skip_records_last_run_at():
    from internal.pump.scheduler import PumpLadderScheduler

    sched = PumpLadderScheduler(refresh_minutes=20)
    sched._running = True

    @contextmanager
    def _busy(_name: str):
        yield False

    with patch("internal.heavy_job_gate.heavy_job_slot", _busy):
        with patch("internal.pump.scheduler._persist_scheduler_meta") as persist:
            result = sched._tick()

    assert result.get("skipped") == "heavy_job_busy"
    assert sched._last_run_at is not None
    persist.assert_called_once()


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
    assert state["last_run_ok"] is True


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
    assert meta.get("scheduler_last_run_ok") is True
    assert meta.get("scheduler_last_result", {}).get("phase_counts") == {"STIRRING": 2}
