"""Tests for the Whale Intelligence service."""

import json

import pytest

from internal.whales.service import WhaleIntelligenceService, TRACKING_DIMENSIONS


@pytest.fixture
def whale_paths(tmp_path):
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
                "alpha_min_win_rate": 0.5,
                "market_mover_min_impact_score": 0.3,
                "conviction_min_hold_hours": 48,
                "rotator_min_subnets": 3,
            }
        )
    )
    return str(config), str(data)


def _seed_alpha_whale(svc: WhaleIntelligenceService, wallet: str, netuid: int = 12):
    """Two winning trades."""
    for day in (1, 2):
        svc.record_event(
            wallet, netuid, "buy", 500.0,
            timestamp=f"2026-07-0{day}T08:00:00+00:00",
            entry_price=1.0,
            market_cap_rank=30,
            total_stake_tao=200000,
        )
        svc.record_event(
            wallet, netuid, "sell", 500.0,
            timestamp=f"2026-07-0{day}T20:00:00+00:00",
            exit_price=1.2,
            price_change_after_hours=15.0,
        )


def _seed_rugger(svc: WhaleIntelligenceService, wallet: str, netuid: int = 18):
    for day in (1, 2):
        svc.record_event(wallet, netuid, "buy", 200.0, timestamp=f"2026-07-0{day}T08:00:00+00:00", entry_price=1.0)
        svc.record_event(wallet, netuid, "sell", 180.0, timestamp=f"2026-07-0{day}T14:00:00+00:00", exit_price=0.85)


def test_dimensions_defined():
    assert "ruggers" in TRACKING_DIMENSIONS
    assert "alpha_whales" in TRACKING_DIMENSIONS
    assert "market_movers" in TRACKING_DIMENSIONS
    assert len(TRACKING_DIMENSIONS) == 6


def test_alpha_whale_classification(whale_paths):
    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    wallet = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    _seed_alpha_whale(svc, wallet)

    profile = svc.get_profile(wallet)
    assert profile["win_rate"] == 1.0
    assert profile["avg_return_pct"] == 20.0
    assert "alpha_whales" in profile["classifications"]


def test_rugger_classification(whale_paths):
    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    wallet = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
    _seed_rugger(svc, wallet)

    profile = svc.get_profile(wallet)
    assert "ruggers" in profile["classifications"]
    assert profile["is_rugger"] is True
    board = svc.get_leaderboard("ruggers")
    assert any(p["wallet"] == wallet for p in board)


def test_market_mover_on_small_cap(whale_paths):
    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    wallet = "5DAAnrj7VHTznn2AWBemMuyVRZ6xZVzgfP8hCskoy4Eccg4"

    svc.record_event(
        wallet, 42, "buy", 50000.0,
        timestamp="2026-07-01T08:00:00+00:00",
        market_cap_rank=15,
        total_stake_tao=100000.0,
    )
    svc.record_event(
        wallet, 42, "sell", 50000.0,
        timestamp="2026-07-03T08:00:00+00:00",
        exit_price=1.3,
        entry_price=1.0,
        market_cap_rank=15,
        total_stake_tao=100000.0,
    )
    svc.record_event(
        wallet, 42, "buy", 50000.0,
        timestamp="2026-07-05T08:00:00+00:00",
        market_cap_rank=15,
        total_stake_tao=100000.0,
    )
    svc.record_event(
        wallet, 42, "sell", 50000.0,
        timestamp="2026-07-07T08:00:00+00:00",
        exit_price=1.4,
        entry_price=1.0,
        market_cap_rank=15,
        total_stake_tao=100000.0,
    )

    profile = svc.get_profile(wallet)
    assert profile["avg_impact_score"] > 0
    assert "market_movers" in profile["classifications"]


def test_rotator_multi_subnet(whale_paths):
    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    wallet = "5HGjWAeFDfFCWPsjFQdVV8M6zmkwDHWi77WcGo9pRn3GTqPC"

    for nuid in (1, 2, 3, 4):
        svc.record_event(wallet, nuid, "buy", 100.0, timestamp=f"2026-07-0{nuid}T08:00:00+00:00")
        svc.record_event(wallet, nuid, "sell", 100.0, timestamp=f"2026-07-0{nuid}T20:00:00+00:00", exit_price=1.1, entry_price=1.0)

    profile = svc.get_profile(wallet)
    assert len(profile["subnets"]) >= 4
    assert "rotators" in profile["classifications"]


def test_alerts_rugger_and_follow(whale_paths):
    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)

    rugger = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
    alpha = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"

    _seed_rugger(svc, rugger)
    _seed_alpha_whale(svc, alpha)

    svc.record_event(rugger, 99, "buy", 300.0, timestamp="2026-07-10T00:00:00+00:00")
    svc.record_event(alpha, 88, "buy", 400.0, timestamp="2026-07-10T00:00:00+00:00")

    alerts = svc.get_active_alerts()
    assert any(a["wallet"] == rugger for a in alerts["rugger_alerts"])
    assert any(a["wallet"] == alpha for a in alerts["follow_alerts"])


def test_subnet_flow(whale_paths):
    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    wallet = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
    _seed_rugger(svc, wallet)
    svc.record_event(wallet, 7, "buy", 250.0, timestamp="2026-07-10T00:00:00+00:00")

    flow = svc.get_subnet_flow(7)
    assert flow["avoid_follow"] is True
    assert len(flow["by_classification"]["ruggers"]) == 1


def test_all_leaderboards(whale_paths):
    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    boards = svc.get_all_leaderboards(limit=10)
    assert set(boards.keys()) == set(TRACKING_DIMENSIONS)


def test_detect_flow_signals_honest_empty(whale_paths):
    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    payload = svc.detect_flow_signals()
    assert payload["data_available"] is False
    assert payload["signals"] == []


def test_detect_flow_signals_accumulation_flip(whale_paths):
    from datetime import datetime, timedelta, timezone

    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    now = datetime.now(timezone.utc)
    wallet = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    svc.record_event(
        wallet,
        64,
        "sell",
        120.0,
        timestamp=(now - timedelta(hours=36)).isoformat(),
        subnet_name="Chutes",
    )
    svc.record_event(
        wallet,
        64,
        "buy",
        200.0,
        timestamp=(now - timedelta(hours=6)).isoformat(),
        subnet_name="Chutes",
    )

    payload = svc.detect_flow_signals(hours=24)
    assert payload["data_available"] is True
    flips = [s for s in payload["signals"] if s.get("kind") == "flow_flip"]
    assert any(s["netuid"] == 64 and s["flip_direction"] == "accumulation" for s in flips)


def test_day_move_highlights_biggest_tao_and_slip(whale_paths):
    from datetime import datetime, timedelta, timezone

    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    now = datetime.now(timezone.utc)
    big = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    thin = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"

    # Larger TAO on deep float
    svc.record_event(
        big,
        7,
        "buy",
        5000.0,
        timestamp=(now - timedelta(hours=2)).isoformat(),
        total_stake_tao=1_000_000.0,
    )
    # Smaller TAO but huge vs thin float → wins slip
    svc.record_event(
        thin,
        7,
        "buy",
        800.0,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        total_stake_tao=10_000.0,
    )
    # Outside window — ignored
    svc.record_event(
        big,
        7,
        "buy",
        50_000.0,
        timestamp=(now - timedelta(hours=30)).isoformat(),
        total_stake_tao=10_000.0,
    )

    out = svc.day_move_highlights(7, hours=24.0)
    assert out["biggest_tao"]["amount_tao"] == 5000.0
    assert out["biggest_tao"]["wallet"] == big
    assert out["biggest_slip"]["wallet"] == thin
    assert out["biggest_slip"]["slip_pct"] == 8.0
    assert out["same_event"] is False
    assert len(out["chips"]) == 2
    assert out["chips"][0].startswith("Day whale")
    assert out["chips"][1].startswith("Biggest slip")


def test_day_move_highlights_same_event_one_chip(whale_paths):
    from datetime import datetime, timedelta, timezone

    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    now = datetime.now(timezone.utc)
    wallet = "5DAAnrj7VHTznn2AWBemMuyVRZ6xZVzgfP8hCskoy4Eccg4"
    svc.record_event(
        wallet,
        9,
        "sell",
        1200.0,
        timestamp=(now - timedelta(hours=3)).isoformat(),
        total_stake_tao=40_000.0,
    )
    out = svc.day_move_highlights(9, liquidity_tao=40_000.0, hours=24.0)
    assert out["same_event"] is True
    assert len(out["chips"]) == 1
    assert "Day whale" in out["chips"][0]
    assert "% float" in out["chips"][0]


def test_day_move_highlights_falls_back_to_7d(whale_paths):
    from datetime import datetime, timedelta, timezone

    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    now = datetime.now(timezone.utc)
    wallet = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    svc.record_event(
        wallet,
        11,
        "buy",
        900.0,
        timestamp=(now - timedelta(hours=36)).isoformat(),
        total_stake_tao=50_000.0,
    )
    out = svc.day_move_highlights(11, hours=24.0)
    assert out["hours"] == 168.0
    assert out["biggest_tao"]["amount_tao"] == 900.0
    assert out["chips"]
