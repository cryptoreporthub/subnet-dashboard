"""Tests for the Ruggers Watchlist (facade over Whale Intelligence)."""

import json

import pytest

from internal.ruggers.watchlist import RuggerWatchlist
from internal.whales.service import WhaleIntelligenceService


@pytest.fixture
def whale_service(tmp_path):
    config = tmp_path / "whales.json"
    data = tmp_path / "intel.json"
    config.write_text(
        json.dumps(
            {
                "flip_thresholds_hours": [6, 24, 72],
                "min_flip_count": 2,
                "min_tao_notional": 10.0,
                "rugger_risk_threshold": 0.5,
                "alpha_min_closed_trades": 2,
            }
        )
    )
    return WhaleIntelligenceService(config_path=str(config), data_path=str(data))


@pytest.fixture
def watchlist(whale_service):
    return RuggerWatchlist(service=whale_service)


def test_record_buy_sell_creates_flip(watchlist):
    watchlist.record_event(
        "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY", 12, "buy", 100.0,
        timestamp="2026-07-01T10:00:00+00:00",
    )
    result = watchlist.record_event(
        "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY", 12, "sell", 95.0,
        timestamp="2026-07-01T14:00:00+00:00",
        exit_price=0.9,
        entry_price=1.0,
    )

    assert result["status"] == "recorded"
    assert result["closed_trade"]["hold_hours"] == 4.0


def test_rugger_flagged_after_multiple_short_flips(watchlist):
    wallet = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"

    for day in (1, 2):
        watchlist.record_event(wallet, 18, "buy", 200.0, timestamp=f"2026-07-0{day}T08:00:00+00:00", entry_price=1.0)
        watchlist.record_event(wallet, 18, "sell", 180.0, timestamp=f"2026-07-0{day}T20:00:00+00:00", exit_price=0.8)

    profile = watchlist.get_profile(wallet)
    assert profile["closed_trades"] == 2
    assert profile["is_rugger"] is True
    assert "ruggers" in profile["classifications"]
    assert len(watchlist.get_watchlist()) == 1


def test_active_alerts_for_open_rugger_position(watchlist):
    wallet = "5DAAnrj7VHTznn2AWBemMuyVRZ6xZVzgfP8hCskoy4Eccg4"

    watchlist.record_event(wallet, 3, "buy", 150.0, timestamp="2026-07-01T00:00:00+00:00", entry_price=1.0)
    watchlist.record_event(wallet, 3, "sell", 140.0, timestamp="2026-07-01T06:00:00+00:00", exit_price=0.85)
    watchlist.record_event(wallet, 3, "buy", 150.0, timestamp="2026-07-02T00:00:00+00:00", entry_price=1.0)
    watchlist.record_event(wallet, 3, "sell", 140.0, timestamp="2026-07-02T08:00:00+00:00", exit_price=0.85)
    watchlist.record_event(wallet, 7, "buy", 300.0, timestamp="2026-07-10T00:00:00+00:00")

    alerts = watchlist.get_active_alerts()
    assert len(alerts) == 1
    assert alerts[0]["wallet"] == wallet
    assert alerts[0]["netuid"] == 7
    assert alerts[0]["recommendation"] == "do_not_follow"


def test_discount_score_when_rugger_present(watchlist):
    wallet = "5HGjWAeFDfFCWPsjFQdVV8M6zmkwDHWi77WcGo9pRn3GTqPC"

    watchlist.record_event(wallet, 5, "buy", 500.0, timestamp="2026-07-01T00:00:00+00:00", entry_price=1.0)
    watchlist.record_event(wallet, 5, "sell", 450.0, timestamp="2026-07-01T03:00:00+00:00", exit_price=0.8)
    watchlist.record_event(wallet, 5, "buy", 500.0, timestamp="2026-07-02T00:00:00+00:00", entry_price=1.0)
    watchlist.record_event(wallet, 5, "sell", 450.0, timestamp="2026-07-02T04:00:00+00:00", exit_price=0.8)
    watchlist.record_event(wallet, 5, "buy", 600.0, timestamp="2026-07-10T00:00:00+00:00")

    adjusted, meta = watchlist.discount_score(5, 0.85)
    assert meta["adjusted"] is True
    assert adjusted < 0.85


def test_scanner_extracts_wallet_from_delegation(monkeypatch, watchlist):
    from internal.ruggers.scanner import scan_subnet_delegations

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
        "internal.whales.scanner.get_subnet_delegation_flow",
        lambda netuid: payload,
    )

    result = scan_subnet_delegations(12, watchlist=watchlist)
    assert result["ingested"] == 1
    assert result["has_wallet_data"] is True
