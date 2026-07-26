"""Pump phase notify (Wave 2 P4) tests."""

from __future__ import annotations

from internal.learning.pump_alert import format_pump_phase_alert, whale_intel_line
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


def test_whale_intel_line_alpha_accumulation():
    flow = {
        "data_available": True,
        "by_classification": {
            "alpha_whales": [{"wallet": "a"}, {"wallet": "b"}],
            "early_movers": [],
            "conviction_holders": [],
            "ruggers": [],
        },
        "smart_money_present": True,
    }

    class _Svc:
        def get_subnet_flow(self, netuid):
            return flow

    import internal.learning.pump_alert as pa

    pa._whale_service_singleton = _Svc()
    out = whale_intel_line(113)
    assert out["wallet_chip"] == "2 whale wallets accumulating"
    assert out["whale_archetype"] == "Alpha whale accumulation"


def test_format_pump_phase_alert_rich_message(monkeypatch):
    monkeypatch.setattr(
        "internal.learning.pump_alert.whale_intel_line",
        lambda netuid: {
            "wallet_chip": "3 whale wallets accumulating",
            "whale_archetype": "Smart money accumulation",
        },
    )
    msg = format_pump_phase_alert(
        netuid=113,
        name="TensorUSD",
        badge="BUILDING",
        phase="ACCUMULATING",
        signal_snapshot={"buy_ratio": 0.68, "volume_intensity": 0.42},
        composite_score=0.74,
    )
    assert "Pump desk · BUILDING" in msg
    assert "TensorUSD SN113" in msg
    assert "3 whale wallets accumulating" in msg
    assert "Smart money accumulation" in msg
    assert "Buy pressure 68%" in msg
    assert "Setup index 74%" in msg
    assert "/subnet/113" in msg


def test_pump_phase_notify_building_dry_run(monkeypatch):
    monkeypatch.setenv("CONVICTION_ALERTS_ENABLED", "on")
    monkeypatch.setenv("CONVICTION_ALERT_DELIVERY", "dry_run")
    monkeypatch.setattr(
        "internal.learning.pump_alert.whale_intel_line",
        lambda netuid: {"wallet_chip": None, "whale_archetype": None},
    )
    out = maybe_notify_pump_phase_entry(
        netuid=7,
        name="Memo",
        badge="BUILDING",
        phase="ACCUMULATING",
        signal_snapshot={"buy_ratio": 0.6},
        composite_score=0.7,
    )
    assert out and out.get("notified") is True
    assert out["delivery"]["delivered"] == 1
    dry = out["delivery"]["dry_run"][0]
    assert "Pump desk · BUILDING" in dry["message"]
    assert "Memo SN7" in dry["message"]
