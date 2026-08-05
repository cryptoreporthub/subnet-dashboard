"""Pump desk GET path — file-backed, no synchronous ladder kick."""

from __future__ import annotations

from unittest.mock import patch


def test_desk_payload_does_not_kick_ladder_on_get(tmp_path, monkeypatch):
    """GET /api/pump-alerts must stay file-backed; refresh runs on scheduler only."""
    monkeypatch.setenv("PUMP_LADDER_STATE_PATH", str(tmp_path / "pump_ladder.json"))
    from internal.pump import constants

    monkeypatch.setattr(constants, "STATE_PATH", str(tmp_path / "pump_ladder.json"))
    from internal.pump.state import save_state as pump_save_state

    pump_save_state({"subnets": {}, "meta": {"last_scan_at": "2020-01-01T00:00:00Z"}})

    with patch("internal.pump.refresh.kick_ladder_fresh") as kick:
        from internal.pump.desk_payload import load_pump_alerts_desk_payload

        payload = load_pump_alerts_desk_payload([])
    kick.assert_not_called()
    assert isinstance(payload, dict)
    assert "status" in payload
