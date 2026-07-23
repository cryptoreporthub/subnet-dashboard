"""TaoStats metrics overlay for pump desk."""

from __future__ import annotations

from internal.learning.pump_alert import build_alert_row
from internal.pump.signals import build_subnet_signals
from internal.pump.taostats_overlay import apply_taostats_overlay, warm_taostats_metrics


def test_apply_taostats_overlay_fills_buy_sell():
    row = {"netuid": 54, "name": "Yanez", "volume": 1000, "buy_volume_24h": 0}
    metrics = {
        "buy_volume_24h": 8000,
        "sell_volume_24h": 2000,
        "fear_and_greed": 62,
        "buys_24hr": 40,
        "sells_24hr": 12,
        "price_change_1h": 0.02,
    }
    out = apply_taostats_overlay(row, metrics)
    assert out["buy_volume_24h"] == 8000
    assert out["sell_volume_24h"] == 2000
    assert out["fear_and_greed"] == 62
    assert out["taostats_wired"] is True
    assert "taostats" in out["sources"]


def test_build_subnet_signals_uses_taostats_flow():
    sig = build_subnet_signals(
        {
            "netuid": 54,
            "name": "Yanez",
            "volume": 50000,
            "emission": 1.0,
            "price": 0.01,
            "price_change_24h": 0.03,
            "buy_volume_24h": 8000,
            "sell_volume_24h": 2000,
            "fear_and_greed": 55,
            "buys_24hr": 30,
            "sells_24hr": 10,
            "price_change_1h": 0.015,
            "taostats_wired": True,
            "sources": ["taomarketcap", "taostats"],
        }
    )
    assert sig["buy_ratio"] == 0.8
    assert sig["fear_and_greed"] == 55
    assert sig["momentum_1h"] == 0.015
    assert sig["taostats_wired"] is True


def test_pump_alert_row_exposes_taostats_metrics():
    row = build_alert_row(
        {
            "netuid": 54,
            "name": "Yanez MIID",
            "phase": "ACCUMULATING",
            "composite_score": 0.5,
            "signal_snapshot": {
                "buy_ratio": 0.7,
                "volume_intensity": 0.4,
                "fear_and_greed": 61,
                "buys_24hr": 22,
                "sells_24hr": 8,
                "taostats_wired": True,
            },
        },
        {
            "netuid": 54,
            "name": "Yanez MIID",
            "buy_volume_24h": 9000,
            "sell_volume_24h": 3000,
            "sources": ["taostats"],
        },
    )
    assert row["fear_and_greed"] == 61
    assert row["buys_24hr"] == 22
    assert row["buy_volume_24h"] == 9000
    assert row["taostats_wired"] is True


def test_warm_taostats_metrics_priority(monkeypatch):
    calls = []

    def fake_metrics(nu):
        calls.append(nu)
        return {"netuid": nu, "fear_and_greed": 50, "buy_volume_24h": 1}

    monkeypatch.setattr(
        "fetchers.taostats_client.is_available", lambda: True
    )
    monkeypatch.setattr(
        "fetchers.taostats_client.get_cached_metrics", lambda nu: None
    )
    monkeypatch.setattr(
        "fetchers.taostats_client.get_subnet_metrics", fake_metrics
    )
    out = warm_taostats_metrics(
        [10, 20, 30, 40],
        priority=[40, 20],
        limit=3,
    )
    assert list(out.keys()) == [40, 20, 10]
    assert calls == [40, 20, 10]
