"""Pump ladder kick uses force when stale."""

from __future__ import annotations

from unittest.mock import patch


def test_desk_payload_kicks_ladder_with_force_when_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("PUMP_LADDER_STATE_PATH", str(tmp_path / "pump_ladder.json"))
    from internal.pump import constants

    monkeypatch.setattr(constants, "STATE_PATH", str(tmp_path / "pump_ladder.json"))
    from internal.pump.state import save_state as pump_save_state

    pump_save_state({"subnets": {}, "meta": {"last_scan_at": "2020-01-01T00:00:00Z"}})

    with patch("internal.pump.refresh.kick_ladder_fresh") as kick:
        from internal.pump.desk_payload import load_pump_alerts_desk_payload

        load_pump_alerts_desk_payload([])
    kick.assert_called_once_with(force=True)
