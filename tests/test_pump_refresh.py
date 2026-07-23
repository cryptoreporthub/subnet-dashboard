"""Pump ladder freshness tests."""

from __future__ import annotations

from unittest.mock import patch

from internal.pump.refresh import ensure_ladder_fresh, ladder_age_minutes
from internal.pump.state import save_state as pump_save_state


def test_ensure_ladder_fresh_skips_when_recent(tmp_path, monkeypatch):
    state_path = str(tmp_path / "pump_ladder.json")
    monkeypatch.setenv("PUMP_LADDER_STATE_PATH", state_path)
    monkeypatch.setenv("PUMP_LADDER_STALE_MINUTES", "30")
    from internal.pump import constants

    monkeypatch.setattr(constants, "STATE_PATH", state_path)
    pump_save_state(
        {
            "subnets": {},
            "meta": {"last_scan_at": "2099-01-01T00:00:00Z"},
        }
    )
    with patch("internal.pump.state.scan_all_subnets") as scan:
        assert ensure_ladder_fresh() is False
        scan.assert_not_called()


def test_ensure_ladder_fresh_scans_when_stale(tmp_path, monkeypatch):
    state_path = str(tmp_path / "pump_ladder.json")
    monkeypatch.setenv("PUMP_LADDER_STATE_PATH", state_path)
    monkeypatch.setenv("PUMP_LADDER_STALE_MINUTES", "1")
    monkeypatch.setenv("PUMP_LADDER_SCAN_COOLDOWN_SECONDS", "0")
    from internal.pump import constants

    monkeypatch.setattr(constants, "STATE_PATH", state_path)
    pump_save_state({"subnets": {}, "meta": {"last_scan_at": "2020-01-01T00:00:00Z"}})
    with patch(
        "internal.pump.state.scan_all_subnets",
        return_value={"ok": True, "scanned": 10, "transitions": []},
    ) as scan:
        assert ensure_ladder_fresh(force=True) is True
        scan.assert_called_once()


def test_ladder_age_minutes_missing_meta(tmp_path, monkeypatch):
    state_path = str(tmp_path / "pump_ladder.json")
    monkeypatch.setenv("PUMP_LADDER_STATE_PATH", state_path)
    from internal.pump import constants

    monkeypatch.setattr(constants, "STATE_PATH", state_path)
    pump_save_state({"subnets": {}, "meta": {}})
    assert ladder_age_minutes() is None
