"""Publish gate + red-team alpha tuning."""

from __future__ import annotations

import pytest

from internal.council.publish_gate import publish_gate_fraction, publish_gate_percent
from internal.council.red_team import audit_daily_pick


def test_publish_gate_defaults_to_45(monkeypatch):
    monkeypatch.delenv("DAILY_PICK_PUBLISH_GATE", raising=False)
    assert publish_gate_fraction() == pytest.approx(0.45)
    assert publish_gate_percent() == 45


def test_publish_gate_env_experiment(monkeypatch):
    monkeypatch.setenv("DAILY_PICK_PUBLISH_GATE", "0.40")
    assert publish_gate_fraction() == pytest.approx(0.40)
    assert publish_gate_percent() == 40


def test_red_team_caps_compound_haircut(monkeypatch):
    monkeypatch.setenv("RED_TEAM_MAX_HAIRCUT", "0.15")
    sn = {
        "netuid": 58,
        "name": "Thin",
        "price": 1.0,
        "volume": 113,
        "status": "at-risk",
        "risk_flags": ["pruning-risk"],
        "confidence": 0.42,
    }
    audit = audit_daily_pick(sn, [sn] * 3)
    # Without cap: 0.96 * 0.90 * 0.85 * ... would crush far below 0.35.
    assert audit["adjusted_confidence"] >= 0.35


def test_red_team_alpha_volume_is_note_not_kill_shot(monkeypatch):
    monkeypatch.setenv("RED_TEAM_MAX_HAIRCUT", "0.15")
    sn = {
        "netuid": 82,
        "name": "Compelle",
        "price": 1.0,
        "volume": 440,
        "confidence": 0.47,
        "status": "active",
    }
    audit = audit_daily_pick(sn, [sn])
    assert audit["adjusted_confidence"] >= 0.45
    assert any("Low liquidity" in c for c in audit["concerns"])


def test_red_team_very_thin_volume_still_audited(monkeypatch):
    monkeypatch.setenv("RED_TEAM_MAX_HAIRCUT", "0.15")
    sn = {
        "netuid": 5,
        "name": "X",
        "price": 1.0,
        "volume": 80,
        "confidence": 0.6,
    }
    audit = audit_daily_pick(sn, [])
    assert any("Very thin volume" in c for c in audit["concerns"])
    assert audit["adjusted_confidence"] >= 0.57
