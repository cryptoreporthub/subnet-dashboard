"""Tests for Telegram calibration snapshot — slot discipline, drift detection, file writes."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_health(factor: float, active: bool = True) -> Dict[str, Any]:
    """Return a minimal calibration_health()-like dict."""
    return {
        "version": "telegram-outcomes-v1",
        "enabled": True,
        "active": active,
        "withheld_reasons": [] if active else ["insufficient_verified_samples"],
        "source": "verified_telegram_24h_outcomes",
        "source_sample_size": 20 if active else 3,
        "verified_resolved_count": 25,
        "hits": 14,
        "hit_rate": 0.70 if active else None,
        "freshness": {"max_age_days": 30, "latest_resolved_at": None, "fresh_sample_size": 20},
        "thresholds": {"min_samples": 10, "min_hit_rate": 0.55, "max_age_days": 30},
        "factor": factor,
    }


# calibration_health is imported *inside* build_calibration_snapshot, so patch
# it at the source module level.
_PATCH_HEALTH = "internal.message_intel.calibration.calibration_health"


# ---------------------------------------------------------------------------
# calibration_snapshot module tests
# ---------------------------------------------------------------------------

class TestBuildCalibrationSnapshot:
    def test_no_previous_snapshot_no_drift(self, tmp_path, monkeypatch):
        """First run: no latest.json → no drift, alert_level reflects calibration status."""
        import internal.message_intel.calibration_snapshot as mod
        monkeypatch.setattr(mod, "_snapshots_dir", lambda: str(tmp_path))

        with patch(_PATCH_HEALTH, return_value=_fake_health(1.05)):
            payload = mod.build_calibration_snapshot()

        assert payload["status"] == "ok"
        drift = payload["drift"]
        assert drift["previous_factor"] is None
        assert drift["drifted"] is False
        assert drift["delta"] == 0.0
        assert payload["alert_level"] == "ok"
        assert payload["alert_reasons"] == []

    def test_drift_below_epsilon_no_warning(self, tmp_path, monkeypatch):
        """Delta below epsilon → drifted=False, alert_level=ok."""
        monkeypatch.setenv("CALIBRATION_SNAPSHOT_DRIFT_EPSILON", "0.01")
        import internal.message_intel.calibration_snapshot as mod
        monkeypatch.setattr(mod, "_snapshots_dir", lambda: str(tmp_path))

        # Persist a previous latest.json with factor=1.05
        prev = {"calibration_health": _fake_health(1.05)}
        (tmp_path / "latest.json").write_text(json.dumps(prev), encoding="utf-8")

        with patch(_PATCH_HEALTH, return_value=_fake_health(1.055)):  # delta=0.005 < 0.01
            payload = mod.build_calibration_snapshot()

        drift = payload["drift"]
        assert drift["drifted"] is False
        assert drift["delta"] < 0.01
        assert payload["alert_level"] == "ok"

    def test_drift_above_epsilon_raises_warn(self, tmp_path, monkeypatch):
        """Delta above epsilon → drifted=True, alert_level=warn, alert_reasons populated."""
        monkeypatch.setenv("CALIBRATION_SNAPSHOT_DRIFT_EPSILON", "0.01")
        import internal.message_intel.calibration_snapshot as mod
        monkeypatch.setattr(mod, "_snapshots_dir", lambda: str(tmp_path))

        prev = {"calibration_health": _fake_health(1.05)}
        (tmp_path / "latest.json").write_text(json.dumps(prev), encoding="utf-8")

        with patch(_PATCH_HEALTH, return_value=_fake_health(1.08)):  # delta=0.03 > 0.01
            payload = mod.build_calibration_snapshot()

        drift = payload["drift"]
        assert drift["drifted"] is True
        assert drift["delta"] > 0.01
        assert payload["alert_level"] == "warn"
        assert any("factor_drift" in r for r in payload["alert_reasons"])

    def test_inactive_calibration_alert_level_warn(self, tmp_path, monkeypatch):
        """Inactive calibration (withheld) → alert_level=warn even without drift."""
        monkeypatch.setenv("CALIBRATION_SNAPSHOT_DRIFT_EPSILON", "0.01")
        import internal.message_intel.calibration_snapshot as mod
        monkeypatch.setattr(mod, "_snapshots_dir", lambda: str(tmp_path))

        with patch(_PATCH_HEALTH, return_value=_fake_health(1.0, active=False)):
            payload = mod.build_calibration_snapshot()

        assert payload["alert_level"] == "warn"
        assert "insufficient_verified_samples" in payload["alert_reasons"]

    def test_save_snapshot_atomic_write(self, tmp_path, monkeypatch):
        """save_snapshot writes both timestamped and latest.json; no leftover .tmp files."""
        import internal.message_intel.calibration_snapshot as mod
        monkeypatch.setattr(mod, "_snapshots_dir", lambda: str(tmp_path))

        payload = {"status": "ok", "captured_at": "2026-08-07T05:15:00Z", "test": True}
        path = mod.save_snapshot(payload)

        # Timestamped file exists and is valid JSON
        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["test"] is True

        # latest.json exists and matches
        latest_path = tmp_path / "latest.json"
        assert latest_path.exists()
        with open(latest_path, encoding="utf-8") as f:
            latest = json.load(f)
        assert latest["test"] is True

        # No leftover .tmp files
        assert list(tmp_path.rglob("*.tmp")) == []

    def test_run_calibration_snapshot_returns_path(self, tmp_path, monkeypatch):
        """run_calibration_snapshot(save=True) includes 'path' in payload."""
        import internal.message_intel.calibration_snapshot as mod
        monkeypatch.setattr(mod, "_snapshots_dir", lambda: str(tmp_path))

        with patch(_PATCH_HEALTH, return_value=_fake_health(1.04)):
            payload = mod.run_calibration_snapshot(save=True)

        assert "path" in payload
        assert os.path.isfile(payload["path"])

    def test_run_calibration_snapshot_no_save(self, tmp_path, monkeypatch):
        """run_calibration_snapshot(save=False) does not write files."""
        import internal.message_intel.calibration_snapshot as mod
        monkeypatch.setattr(mod, "_snapshots_dir", lambda: str(tmp_path))

        with patch(_PATCH_HEALTH, return_value=_fake_health(1.04)):
            payload = mod.run_calibration_snapshot(save=False)

        assert "path" not in payload
        assert list(tmp_path.rglob("*.json")) == []


# ---------------------------------------------------------------------------
# calibration_snapshot_scheduler — slot discipline tests
# ---------------------------------------------------------------------------

class TestCalibrationSnapshotSchedulerSlot:
    """Verify the scheduler anchors first and subsequent ticks to the UTC slot."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        import internal.message_intel.calibration_snapshot_scheduler as smod
        smod._scheduler = None
        yield
        smod._scheduler = None

    def test_seconds_until_slot_future_today(self):
        """When the slot is still in the future today, result is hours away."""
        import internal.message_intel.calibration_snapshot_scheduler as smod

        # 02:00 UTC, slot 05:15 UTC → ~3h 15m
        now = datetime(2026, 8, 7, 2, 0, 0, tzinfo=timezone.utc)
        secs = smod._seconds_until_slot(now)
        expected = 3 * 3600 + 15 * 60  # 11700
        assert abs(secs - expected) < 2

    def test_seconds_until_slot_past_today_wraps_tomorrow(self):
        """When the slot has already passed today, result points to tomorrow's slot."""
        import internal.message_intel.calibration_snapshot_scheduler as smod

        # 06:00 UTC, slot 05:15 UTC → ~23h 15m until tomorrow
        now = datetime(2026, 8, 7, 6, 0, 0, tzinfo=timezone.utc)
        secs = smod._seconds_until_slot(now)
        expected = 23 * 3600 + 15 * 60  # 83700
        assert abs(secs - expected) < 2

    def test_start_schedules_at_slot_not_120s(self, monkeypatch):
        """start() must use _seconds_until_slot(), not min(120, slot)."""
        import internal.message_intel.calibration_snapshot_scheduler as smod

        scheduled_delays = []
        monkeypatch.setattr(smod, "schedule_in_seconds", lambda jid, fn, delay: scheduled_delays.append(delay))

        slot_delay = 3 * 3600 + 15 * 60  # 11700

        with patch.object(smod, "_seconds_until_slot", return_value=float(slot_delay)), \
             patch.object(smod, "_next_slot_dt", return_value=datetime(2026, 8, 7, 5, 15, 0, tzinfo=timezone.utc)):
            sched = smod.CalibrationSnapshotScheduler()
            sched.start(immediate=False)

        assert len(scheduled_delays) == 1
        assert scheduled_delays[0] == float(slot_delay), (
            f"Expected slot-anchored delay {slot_delay}, got {scheduled_delays[0]}. "
            "Scheduler must not cap to 120s."
        )

    def test_tick_reschedules_at_slot_not_fixed_interval(self, tmp_path, monkeypatch):
        """After a tick, the next schedule uses _seconds_until_slot(), not a fixed 24h delta."""
        import internal.message_intel.calibration_snapshot_scheduler as smod
        import internal.message_intel.calibration_snapshot as csmod
        monkeypatch.setattr(csmod, "_snapshots_dir", lambda: str(tmp_path))

        scheduled_delays = []
        monkeypatch.setattr(smod, "schedule_in_seconds", lambda jid, fn, delay: scheduled_delays.append(delay))

        slot_delay = 3 * 3600 + 15 * 60  # 11700

        with patch(_PATCH_HEALTH, return_value=_fake_health(1.04)), \
             patch.object(smod, "_seconds_until_slot", return_value=float(slot_delay)), \
             patch.object(smod, "_next_slot_dt", return_value=datetime(2026, 8, 8, 5, 15, 0, tzinfo=timezone.utc)):
            s = smod.CalibrationSnapshotScheduler()
            s._active = True
            s._tick(reschedule=True)

        assert len(scheduled_delays) == 1
        assert scheduled_delays[0] == float(slot_delay), (
            f"After tick, must re-anchor to slot delay {slot_delay}s, got {scheduled_delays[0]}. "
            "Must not use a fixed 24h interval."
        )

    def test_state_includes_next_run_at(self, monkeypatch):
        """Scheduler state must expose next_run_at for operator visibility."""
        import internal.message_intel.calibration_snapshot_scheduler as smod

        monkeypatch.setattr(smod, "schedule_in_seconds", lambda *a: None)
        next_dt = datetime(2026, 8, 7, 5, 15, 0, tzinfo=timezone.utc)

        with patch.object(smod, "_seconds_until_slot", return_value=11700.0), \
             patch.object(smod, "_next_slot_dt", return_value=next_dt):
            s = smod.CalibrationSnapshotScheduler()
            s.start(immediate=False)

        state = s.state()
        assert "next_run_at" in state
        assert state["next_run_at"] is not None
        # Should contain the date or time portion of the next slot
        assert "2026-08-07" in state["next_run_at"]

    def test_disabled_env_skips_start(self, monkeypatch):
        """CALIBRATION_SNAPSHOT_ENABLED=off must return started=False."""
        import internal.message_intel.calibration_snapshot_scheduler as smod
        monkeypatch.setenv("CALIBRATION_SNAPSHOT_ENABLED", "off")

        result = smod.start_calibration_snapshot_scheduler()
        assert result["started"] is False
        assert result["reason"] == "disabled"

    def test_run_once_tick_result_keys(self, tmp_path, monkeypatch):
        """run_once() (reschedule=False) returns expected result keys and values."""
        import internal.message_intel.calibration_snapshot_scheduler as smod
        import internal.message_intel.calibration_snapshot as csmod
        monkeypatch.setattr(csmod, "_snapshots_dir", lambda: str(tmp_path))
        monkeypatch.setattr(smod, "schedule_in_seconds", lambda *a: None)

        with patch(_PATCH_HEALTH, return_value=_fake_health(1.04)):
            s = smod.CalibrationSnapshotScheduler()
            result = s.run_once()

        assert result["ok"] is True
        assert "alert_level" in result
        assert "drifted" in result
        assert "factor" in result
        assert "path" in result
        assert result["alert_level"] in ("ok", "warn", "alert")
        assert isinstance(result["drifted"], bool)
        # No next_run_at when reschedule=False
        assert "next_run_at" not in result

    def test_run_once_drift_above_epsilon_flows_through_tick(self, tmp_path, monkeypatch):
        """Scheduler run_once() with a seeded prior snapshot + shifted factor reports drifted=True and alert_level=warn."""
        monkeypatch.setenv("CALIBRATION_SNAPSHOT_DRIFT_EPSILON", "0.01")
        import internal.message_intel.calibration_snapshot_scheduler as smod
        import internal.message_intel.calibration_snapshot as csmod
        monkeypatch.setattr(csmod, "_snapshots_dir", lambda: str(tmp_path))
        monkeypatch.setattr(smod, "schedule_in_seconds", lambda *a: None)

        # Seed a previous latest.json with factor=1.05
        prev = {"calibration_health": _fake_health(1.05)}
        (tmp_path / "latest.json").write_text(json.dumps(prev), encoding="utf-8")

        # Run the tick with factor=1.09 (delta=0.04 > epsilon=0.01)
        with patch(_PATCH_HEALTH, return_value=_fake_health(1.09)):
            s = smod.CalibrationSnapshotScheduler()
            result = s.run_once()

        assert result["ok"] is True
        assert result["drifted"] is True
        assert result["alert_level"] == "warn"
        # latest.json must be updated with the new snapshot
        latest = json.loads((tmp_path / "latest.json").read_text())
        assert latest["drift"]["drifted"] is True
        drift_reasons = latest["alert_reasons"]
        assert any("factor_drift" in r for r in drift_reasons)

    def test_run_once_snapshot_failure_returns_error_and_does_not_raise(self, tmp_path, monkeypatch):
        """A failing snapshot invocation returns ok=False with error key; tick does not raise or reschedule."""
        import internal.message_intel.calibration_snapshot_scheduler as smod
        import internal.message_intel.calibration_snapshot as csmod
        monkeypatch.setattr(csmod, "_snapshots_dir", lambda: str(tmp_path))

        scheduled_calls = []
        monkeypatch.setattr(smod, "schedule_in_seconds", lambda *a: scheduled_calls.append(a))

        def _boom(**kwargs):
            raise RuntimeError("calibration db unavailable")

        with patch("internal.message_intel.calibration_snapshot.run_calibration_snapshot", side_effect=_boom):
            s = smod.CalibrationSnapshotScheduler()
            result = s.run_once()  # reschedule=False

        assert result["ok"] is False
        assert "error" in result
        assert "calibration db unavailable" in result["error"]
        # reschedule=False: schedule_in_seconds must NOT have been called
        assert scheduled_calls == []


def test_calibration_snapshot_scheduler_tracker_is_liveness_compliant(monkeypatch, tmp_path):
    from tests.liveness_conformance import assert_liveness_compliant
    import internal.message_intel.calibration_snapshot_scheduler as smod

    soul = tmp_path / "soul_map.json"
    soul.write_text("{}")
    monkeypatch.setenv("SOUL_MAP_PATH", str(soul))

    def factory():
        return smod.CalibrationSnapshotScheduler().liveness

    assert_liveness_compliant(factory)
