"""Pump phase notify (Wave 2 P4) tests."""

from __future__ import annotations

from internal.learning.pump_phase_notify import (
    maybe_notify_pump_phase_entry,
    pump_phase_alerts_enabled,
)


def test_pump_phase_notify_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CONVICTION_ALERTS_ENABLED", raising=False)
    assert pump_phase_alerts_enabled() is False
    assert maybe_notify_pump_phase_entry(netuid=1, name="Test", badge="BUILDING", phase="ACCUMULATING") is None


def test_pump_phase_notify_skips_chase_risk(monkeypatch):
    monkeypatch.setenv("CONVICTION_ALERTS_ENABLED", "on")
    monkeypatch.setenv("CONVICTION_ALERT_DELIVERY", "dry_run")
    out = maybe_notify_pump_phase_entry(netuid=2, name="Test", badge="CHASE RISK", phase="PUMPING")
    assert out is None
