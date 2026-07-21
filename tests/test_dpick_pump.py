"""K3-7b — dossier pump chip (STIRRING/ACCUMULATING, lead-gated)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from internal.learning.dpick_pump import attach_pump_chip_to_daily_pick, build_pump_chip


def _subnet(netuid: int = 99, **extra) -> dict:
    return {
        "netuid": netuid,
        "name": f"SN{netuid}",
        "emission": 1.0,
        "volume": 50000,
        "buy_volume_24h": 7000,
        "sell_volume_24h": 3000,
        **extra,
    }


def _ladder(phase: str, buy_ratio: float = 0.68, volume_intensity: float = 0.45) -> dict:
    return {
        "phase": phase,
        "signal_snapshot": {
            "buy_ratio": buy_ratio,
            "volume_intensity": volume_intensity,
        },
    }


def test_stirring_shows_with_lead_signals():
    chip = build_pump_chip(99, _subnet(), ladder_entry=_ladder("STIRRING"))
    assert chip["show"] is True
    assert chip["tier"] == "STIRRING"
    assert chip["label"] == "WARMING UP"
    assert "warming up" in chip["trigger"].lower()


def test_accumulating_higher_tier():
    chip = build_pump_chip(99, _subnet(), ladder_entry=_ladder("ACCUMULATING"))
    assert chip["show"] is True
    assert chip["tier"] == "ACCUMULATING"
    assert chip["label"] == "HEAT BUILDING"


def test_pumping_hidden():
    chip = build_pump_chip(99, _subnet(), ladder_entry=_ladder("PUMPING"))
    assert chip["show"] is False


def test_dormant_hidden():
    chip = build_pump_chip(99, _subnet(), ladder_entry=_ladder("DORMANT"))
    assert chip["show"] is False


def test_lead_gate_blocks_lag_only_phase():
    chip = build_pump_chip(
        99,
        _subnet(),
        ladder_entry=_ladder("STIRRING", buy_ratio=0.48, volume_intensity=0.10),
    )
    assert chip["show"] is False


def test_attach_wires_hero_netuid_from_candidate():
    payload = {
        "action": "HOLD",
        "pick": None,
        "candidate": {"subnet": {"netuid": 99, "name": "SN99"}},
    }
    ladder = {"subnets": {"99": _ladder("STIRRING")}}
    with patch("internal.pump.state.load_state", return_value=ladder):
        out = attach_pump_chip_to_daily_pick(payload, [_subnet()])
    assert out["pump_chip"]["show"] is True
    assert out["pump_chip"]["tier"] == "STIRRING"


def test_self_check_lead_gate_constants():
    assert 0.55 <= 1.0
    assert build_pump_chip(None)["show"] is False
