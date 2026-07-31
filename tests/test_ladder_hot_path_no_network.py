"""Regression: reading pump-ladder / pump-alerts data must never trigger a live
TaoStats network call — that wedged the FastAPI event loop in production
(rate-limited time.sleep() running synchronously on the request thread).
"""

from __future__ import annotations

from unittest.mock import patch

from internal.pump.state import save_state as pump_save_state
from internal.pump.state import get_ladder_snapshot


def _ladder_state():
    return {
        "version": "1.0",
        "subnets": {
            "99999": {
                "netuid": 99999,
                "name": "Coldint",
                "phase": "ACCUMULATING",
                "since": "2026-07-01T00:00:00Z",
                "composite_score": 0.5,
                "transitions": [],
            }
        },
        "meta": {},
    }


def test_ladder_snapshot_never_calls_taostats_identity(tmp_path, monkeypatch):
    state_path = str(tmp_path / "pump_ladder.json")
    monkeypatch.setenv("PUMP_LADDER_STATE_PATH", state_path)
    from internal.pump import constants

    monkeypatch.setattr(constants, "STATE_PATH", state_path)
    pump_save_state(_ladder_state(), path=state_path)

    with patch("fetchers.taostats_client.get_subnet_identity") as identity:
        snapshot = get_ladder_snapshot(path=state_path)

    identity.assert_not_called()
    assert snapshot["subnets"][0]["name"] == "Coldint"


def test_pump_alerts_desk_never_calls_taostats_identity():
    from internal.learning.pump_alert import build_pump_alerts_desk

    ladder = {
        "subnets": {
            "29": {
                "netuid": 29,
                "name": "Coldint",
                "phase": "PUMPING",
                "current_phase": "PUMPING",
                "composite_score": 0.81,
                "since": "2026-07-01T00:00:00Z",
                "transitions": [],
            }
        }
    }
    with patch("internal.pump.state.load_state", return_value=ladder):
        with patch("fetchers.taostats_client.get_subnet_identity") as identity:
            build_pump_alerts_desk([])

    identity.assert_not_called()
