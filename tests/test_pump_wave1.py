"""Wave 1 pump triad + size cliff tests."""

from __future__ import annotations

from internal.learning.pump_alert import build_alert_row
from internal.learning.pump_lead_stats import build_pump_desk_trust
from internal.pump.triad import (
    compute_pump_triad,
    price_coil,
    tao_inflow_quiet_load,
)


def test_tao_inflow_quiet_load_detects_flow_before_price():
    signals = {
        "buy_ratio": 0.62,
        "volume_intensity": 0.25,
        "momentum_1h": 0.004,
        "price_change_24h": 0.01,
    }
    assert tao_inflow_quiet_load(signals) is True


def test_price_coil_after_drawdown():
    signals = {"price_change_24h": -0.05, "momentum_1h": -0.001}
    assert price_coil(signals) is True


def test_strong_triad_when_all_three_lit():
    triad = compute_pump_triad(
        {
            "buy_ratio": 0.68,
            "volume_intensity": 0.3,
            "momentum_1h": 0.003,
            "price_change_24h": -0.04,
        },
        buy_ratio_min=0.55,
    )
    assert triad["lit_count"] == 3
    assert triad["strength"] == "STRONG"


def test_alert_row_strong_badge_when_triad_full():
    entry = {
        "netuid": 42,
        "name": "Test",
        "phase": "ACCUMULATING",
        "composite_score": 0.48,
        "signal_snapshot": {
            "buy_ratio": 0.68,
            "volume_intensity": 0.3,
            "momentum_1h": 0.003,
            "price_change_24h": -0.04,
            "triad": {
                "inflow_quiet_load": True,
                "buy_pressure": True,
                "price_coil": True,
                "lit_count": 3,
                "strength": "STRONG",
            },
        },
    }
    subnet = {"netuid": 42, "name": "Test", "market_cap": 5000, "price": 1.0, "volume": 200}
    row = build_alert_row(entry, subnet)
    assert row["badge"] == "STRONG"
    assert row["triad"]["lit_count"] == 3
    assert row["size_line"] and "50 τ" in row["size_line"]
    assert "thin" in row["size_line"] or "healthy" in row["size_line"]


def test_trust_headline_when_sample_ready():
    rows = [
        {
            "pick_source": "pump_lead",
            "pump_claim": "ACCUMULATING",
            "pump_badge": "BUILDING",
            "correct": True,
            "outcome": "hit",
            "actual_pct": 2.5,
        }
        for _ in range(6)
    ]
    trust = build_pump_desk_trust({"resolved": rows, "predictions": []})
    assert trust["ready"] is True
    assert trust["headline_pct"] is not None
    assert trust["headline_n"] == 6
