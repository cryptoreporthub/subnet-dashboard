"""Tests for the Ruggers Watchlist."""

import json
import os
import tempfile

import pytest

from internal.ruggers.watchlist import RuggerWatchlist


@pytest.fixture
def watchlist_paths(tmp_path):
    config = tmp_path / "ruggers.json"
    data = tmp_path / "watchlist.json"
    config.write_text(
        json.dumps(
            {
                "flip_thresholds_hours": [6, 24, 72],
                "min_flip_count": 2,
                "min_tao_notional": 10.0,
                "rugger_risk_threshold": 0.5,
            }
        )
    )
    return str(config), str(data)


def test_record_buy_sell_creates_flip(watchlist_paths):
    config_path, data_path = watchlist_paths
    wl = RuggerWatchlist(config_path=config_path, data_path=data_path)

    wl.record_event("5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY", 12, "buy", 100.0,
                    timestamp="2026-07-01T10:00:00+00:00")
    result = wl.record_event("5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY", 12, "sell", 95.0,
                             timestamp="2026-07-01T14:00:00+00:00")

    assert result["status"] == "recorded"
    assert result["flip"]["hold_hours"] == 4.0
    profile = wl.get_profile("5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY")
    assert profile["flip_count"] == 1
    assert profile["median_hold_hours"] == 4.0


def test_rugger_flagged_after_multiple_short_flips(watchlist_paths):
    config_path, data_path = watchlist_paths
    wl = RuggerWatchlist(config_path=config_path, data_path=data_path)
    wallet = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"

    for day in (1, 2):
        wl.record_event(wallet, 18, "buy", 200.0, timestamp=f"2026-07-0{day}T08:00:00+00:00")
        wl.record_event(wallet, 18, "sell", 180.0, timestamp=f"2026-07-0{day}T20:00:00+00:00")

    profile = wl.get_profile(wallet)
    assert profile["flip_count"] == 2
    assert profile["is_rugger"] is True
    assert "rugger" in profile["tags"]
    assert len(wl.get_watchlist()) == 1


def test_active_alerts_for_open_rugger_position(watchlist_paths):
    config_path, data_path = watchlist_paths
    wl = RuggerWatchlist(config_path=config_path, data_path=data_path)
    wallet = "5DAAnrj7VHTznn2AWBemMuyVRZ6xZVzgfP8hCskoy4Eccg4"

    wl.record_event(wallet, 3, "buy", 150.0, timestamp="2026-07-01T00:00:00+00:00")
    wl.record_event(wallet, 3, "sell", 140.0, timestamp="2026-07-01T06:00:00+00:00")
    wl.record_event(wallet, 3, "buy", 150.0, timestamp="2026-07-02T00:00:00+00:00")
    wl.record_event(wallet, 3, "sell", 140.0, timestamp="2026-07-02T08:00:00+00:00")
    wl.record_event(wallet, 7, "buy", 300.0, timestamp="2026-07-10T00:00:00+00:00")

    alerts = wl.get_active_alerts()
    assert len(alerts) == 1
    assert alerts[0]["wallet"] == wallet
    assert alerts[0]["netuid"] == 7
    assert alerts[0]["recommendation"] in ("do_not_follow", "exit_before_median")


def test_discount_score_when_rugger_present(watchlist_paths):
    config_path, data_path = watchlist_paths
    wl = RuggerWatchlist(config_path=config_path, data_path=data_path)
    wallet = "5HGjWAeFDfFCWPsjFQdVV8M6zmkwDHWi77WcGo9pRn3GTqPC"

    wl.record_event(wallet, 5, "buy", 500.0, timestamp="2026-07-01T00:00:00+00:00")
    wl.record_event(wallet, 5, "sell", 450.0, timestamp="2026-07-01T03:00:00+00:00")
    wl.record_event(wallet, 5, "buy", 500.0, timestamp="2026-07-02T00:00:00+00:00")
    wl.record_event(wallet, 5, "sell", 450.0, timestamp="2026-07-02T04:00:00+00:00")
    wl.record_event(wallet, 5, "buy", 600.0, timestamp="2026-07-10T00:00:00+00:00")

    adjusted, meta = wl.discount_score(5, 0.85)
    assert meta["adjusted"] is True
    assert adjusted < 0.85


def test_scanner_extracts_wallet_from_delegation(monkeypatch, watchlist_paths):
    from internal.ruggers.scanner import scan_subnet_delegations

    config_path, data_path = watchlist_paths
    wl = RuggerWatchlist(config_path=config_path, data_path=data_path)

    payload = {
        "data": [
            {
                "coldkey": "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
                "amount": 250,
                "direction": "stake",
                "timestamp": "2026-07-10T12:00:00+00:00",
            }
        ]
    }

    monkeypatch.setattr(
        "internal.ruggers.scanner.get_subnet_delegation_flow",
        lambda netuid: payload,
    )

    result = scan_subnet_delegations(12, watchlist=wl)
    assert result["ingested"] == 1
    assert result["has_wallet_data"] is True
