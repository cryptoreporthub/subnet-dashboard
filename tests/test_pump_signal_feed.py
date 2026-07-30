"""Pump signal feed must not score all DORMANT on price-only live rows."""

from __future__ import annotations

from unittest.mock import patch

from internal.pump.engine import compute_composite_score, raw_phase_from_score
from internal.pump.taostats_overlay import load_subnets_for_pump_signals


def test_load_subnets_overlays_tmc_when_flow_missing():
    live_only = [
        {"netuid": 1, "name": "Apex", "price": 0.01, "emission": 1.0},
        {"netuid": 2, "name": "Omron", "price": 0.02, "emission": 1.0},
    ]
    tmc = [
        {
            "netuid": 1,
            "name": "Apex",
            "price": 0.01,
            "volume": 500000,
            "price_change_24h": 8.5,
            "emission": 1.0,
        },
        {
            "netuid": 2,
            "name": "Omron",
            "price": 0.02,
            "volume": 200000,
            "price_change_24h": -3.2,
            "emission": 1.0,
        },
    ]
    with patch("fetchers.merged_data._get_cached", return_value=None):
        with patch("fetchers.taomarketcap.get_all_subnets", return_value=[]):
            with patch("fetchers.merged_data.get_merged_subnet_data", return_value=live_only):
                with patch("fetchers.taomarketcap._get_all_subnets_tao", return_value=tmc):
                    with patch("internal.pump.taostats_overlay.warm_taostats_metrics", return_value={}):
                        rows = load_subnets_for_pump_signals()
    assert rows[0].get("volume") == 500000
    assert rows[0].get("price_change_24h") == 8.5
    sig = {
        "price_change_24h": float(rows[0]["price_change_24h"]),
        "momentum_1h": float(rows[0]["price_change_24h"]) / 8.0,
        "volume_intensity": 0.3,
        "buy_ratio": 0.55,
        "chatter_intensity": 0,
    }
    score = compute_composite_score(sig)
    assert score > 0.22
    assert raw_phase_from_score(score) != "DORMANT"


def test_load_subnets_uses_tmc_before_blocking_merge():
    tmc_rows = [{"netuid": 9, "name": "Nine", "price": 1.0, "volume": 1000, "emission": 1.0}]
    with patch("fetchers.merged_data._get_cached", return_value=None):
        with patch("fetchers.taomarketcap.get_all_subnets", return_value=tmc_rows) as tmc:
            with patch("fetchers.merged_data.get_merged_subnet_data") as merged:
                with patch("internal.pump.taostats_overlay.warm_taostats_metrics", return_value={}):
                    rows = load_subnets_for_pump_signals()
    tmc.assert_called_once()
    merged.assert_not_called()
    assert rows[0]["netuid"] == 9
