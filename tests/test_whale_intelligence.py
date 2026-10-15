"""Tests for the Whale Intelligence service."""

import json
import multiprocessing as mp
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from internal.whales.service import WhaleIntelligenceService, TRACKING_DIMENSIONS
from internal.whales.scanner import scan_subnet_delegations


def _mp_record_whale_events(config_path: str, data_path: str, prefix: str) -> None:
    svc = WhaleIntelligenceService(config_path=config_path, data_path=data_path)
    for i in range(10):
        svc.record_event(
            f"5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQ{i}",
            1,
            "buy",
            50.0,
            tx_hash=f"{prefix}-{i}",
        )


@pytest.fixture
def whale_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("WHALE_EVENT_RETENTION_DAYS", "0")
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


def test_save_data_uses_sidecar_tmp_not_mkstemp_json(whale_paths):
    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    _seed_alpha_whale(svc, "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY")

    data_dir = Path(data).parent
    assert not list(data_dir.glob("tmp*.json"))
    assert Path(data).exists()
    assert not list(data_dir.glob(f"{Path(data).name}.*.*.tmp"))


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


def test_batch_defers_single_save(whale_paths):
    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    saves = []
    with patch.object(svc, "_save_data", side_effect=lambda: saves.append(1)):
        with svc.batch():
            for i in range(5):
                svc.record_event(
                    f"5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQ{i}",
                    1,
                    "buy",
                    100.0,
                    timestamp=f"2026-07-01T08:00:{i:02d}+00:00",
                    tx_hash=f"hash-{i}",
                )
    assert len(saves) == 1


def test_idempotent_replay_by_tx_hash(whale_paths):
    from datetime import datetime, timezone

    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    wallet = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    ts = datetime.now(timezone.utc).isoformat()
    kwargs = {
        "wallet": wallet,
        "netuid": 3,
        "side": "buy",
        "amount_tao": 120.0,
        "timestamp": ts,
        "tx_hash": "same-tx",
    }
    first = svc.record_event(**kwargs)
    second = svc.record_event(**kwargs)
    assert first["status"] == "recorded"
    assert second["status"] == "ignored"
    assert second["reason"] == "duplicate"
    assert len(svc.data["events"]) == 1
    assert len(svc.data["closed_trades"]) == 0


def test_retention_prunes_old_events_only(whale_paths, monkeypatch):
    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    monkeypatch.setenv("WHALE_EVENT_RETENTION_DAYS", "30")
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    svc.data["events"] = [
        {
            "wallet": "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
            "netuid": 1,
            "side": "buy",
            "amount_tao": 50.0,
            "timestamp": (now - timedelta(days=120)).isoformat(),
        },
        {
            "wallet": "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty",
            "netuid": 2,
            "side": "buy",
            "amount_tao": 60.0,
            "timestamp": (now - timedelta(days=2)).isoformat(),
            "tx_hash": "keep-me",
        },
    ]
    svc.data["profiles"] = {"keeper": {"wallet": "keeper", "closed_trades": 1}}
    svc._rebuild_event_keys()
    svc._prune_events_retention()
    assert len(svc.data["events"]) == 1
    assert svc.data["events"][0]["tx_hash"] == "keep-me"
    assert svc.data["profiles"]["keeper"]["closed_trades"] == 1


def test_record_event_naive_iso_timestamp_with_retention(whale_paths, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from fastapi.testclient import TestClient

    config, data = whale_paths
    monkeypatch.setenv("WHALE_EVENT_RETENTION_DAYS", "90")
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    wallet = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    recent_naive = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    out = svc.record_event(
        wallet, 1, "buy", 100.0, timestamp=recent_naive, tx_hash="naive-recent"
    )
    assert out["status"] == "recorded"

    old_naive = (datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%S")
    ignored = svc.record_event(
        wallet, 1, "sell", 100.0, timestamp=old_naive, tx_hash="naive-stale"
    )
    assert ignored["status"] == "ignored"
    assert ignored["reason"] == "older_than_retention"

    from fastapi import FastAPI

    from internal.whales.routes import whales_router

    monkeypatch.setattr("internal.whales.routes.get_whale_service", lambda: svc)
    app = FastAPI()
    app.include_router(whales_router)

    with TestClient(app) as client:
        resp = client.post(
            "/api/whales/events",
            json={
                "wallet": wallet,
                "netuid": 2,
                "side": "buy",
                "amount_tao": 100.0,
                "timestamp": recent_naive,
                "tx_hash": "naive-api",
            },
        )
    assert resp.status_code == 200
    assert resp.json().get("status") == "recorded"
    stored = json.loads(Path(data).read_text())
    assert any(e.get("tx_hash") == "naive-api" for e in stored.get("events", []))


def test_old_event_reingest_ignored_after_retention_prune(whale_paths, monkeypatch):
    from datetime import datetime, timedelta, timezone

    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    monkeypatch.setenv("WHALE_EVENT_RETENTION_DAYS", "30")
    wallet = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    now = datetime.now(timezone.utc)
    recent_ts = (now - timedelta(days=1)).isoformat()
    old_ts = (now - timedelta(days=120)).isoformat()

    svc.record_event(wallet, 7, "buy", 100.0, timestamp=recent_ts, tx_hash="recent-open")
    pos_key = f"{wallet}:7"
    assert pos_key in svc.data["open_positions"]

    svc._prune_events_retention()
    assert len(svc.data["events"]) == 1
    svc._event_keys.clear()

    replay = svc.record_event(
        wallet,
        7,
        "sell",
        100.0,
        timestamp=old_ts,
        tx_hash="stale-scanner-row",
    )
    assert replay["status"] == "ignored"
    assert replay["reason"] == "older_than_retention"
    assert pos_key in svc.data["open_positions"]
    assert len(svc.data["events"]) == 1


def test_transaction_releases_flock_when_save_fails(whale_paths):
    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    releases: list[int] = []
    real_release = svc._flock_release

    def counting_release() -> None:
        releases.append(1)
        real_release()

    with patch.object(svc, "_save_data", side_effect=OSError("disk full")):
        with patch.object(svc, "_flock_release", side_effect=counting_release):
            with pytest.raises(OSError, match="disk full"):
                with svc.transaction():
                    svc._dirty = True
    assert len(releases) == 1


def test_compact_json_write(whale_paths, monkeypatch):
    config, data = whale_paths
    monkeypatch.setenv("WHALE_JSON_COMPACT", "on")
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    svc.record_event(
        "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
        1,
        "buy",
        10.0,
        tx_hash="compact-1",
    )
    raw = Path(data).read_text()
    assert "\n  " not in raw
    loaded = json.loads(raw)
    assert loaded["events"]


def test_loads_legacy_indented_file(whale_paths, monkeypatch):
    config, data = whale_paths
    payload = {
        "updated_at": "2026-07-01T00:00:00+00:00",
        "events": [
            {
                "wallet": "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
                "netuid": 9,
                "side": "buy",
                "amount_tao": 25.0,
                "timestamp": "2026-07-01T08:00:00+00:00",
            }
        ],
        "open_positions": {},
        "profiles": {},
        "closed_trades": [],
    }
    Path(data).write_text(json.dumps(payload, indent=2))
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    assert len(svc.data["events"]) == 1


def test_singleton_threads_keep_all_events(whale_paths, tmp_path):
    from datetime import datetime, timedelta, timezone

    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    base = datetime.now(timezone.utc)

    def worker(start: int):
        for i in range(10):
            svc.record_event(
                f"5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQ{start + i}",
                1,
                "buy",
                50.0,
                timestamp=(base + timedelta(seconds=start + i)).isoformat(),
                tx_hash=f"t-{start}-{i}",
            )

    threads = [threading.Thread(target=worker, args=(n * 10,)) for n in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(svc.data["events"]) == 20


def test_nested_transaction_flock_release_once(whale_paths):
    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    acquires: list[int] = []
    releases: list[int] = []

    real_acquire = svc._flock_acquire
    real_release = svc._flock_release

    def counting_acquire() -> None:
        acquires.append(1)
        real_acquire()

    def counting_release() -> None:
        releases.append(1)
        real_release()

    with patch.object(svc, "_flock_acquire", side_effect=counting_acquire):
        with patch.object(svc, "_flock_release", side_effect=counting_release):
            with svc.transaction():
                svc.record_event(
                    "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
                    1,
                    "buy",
                    100.0,
                    tx_hash="nested-route-tx",
                )
    assert len(acquires) == 1
    assert len(releases) == 1


def test_transaction_acquire_failure_resets_depth(whale_paths):
    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    acquire_attempts: list[int] = []

    def failing_acquire() -> None:
        acquire_attempts.append(1)
        raise OSError("flock blocked")

    with patch.object(svc, "_flock_acquire", side_effect=failing_acquire):
        with pytest.raises(OSError, match="flock blocked"):
            with svc.transaction():
                pass
    assert svc._transaction_depth == 0
    assert len(acquire_attempts) == 1

    acquire_attempts.clear()
    with patch.object(svc, "_flock_acquire", side_effect=failing_acquire):
        with pytest.raises(OSError, match="flock blocked"):
            with svc.transaction():
                pass
    assert svc._transaction_depth == 0
    assert len(acquire_attempts) == 1


def test_two_process_same_path_no_lost_updates(whale_paths):
    config, data = whale_paths
    ctx = mp.get_context("spawn")
    workers = [
        ctx.Process(target=_mp_record_whale_events, args=(config, data, "a")),
        ctx.Process(target=_mp_record_whale_events, args=(config, data, "b")),
    ]
    for proc in workers:
        proc.start()
    for proc in workers:
        proc.join()
    assert all(proc.exitcode == 0 for proc in workers)
    loaded = json.loads(Path(data).read_text())
    assert len(loaded["events"]) == 20


def test_scan_subnet_batch_one_save(whale_paths, monkeypatch):
    from datetime import datetime, timezone

    config, data = whale_paths
    svc = WhaleIntelligenceService(config_path=config, data_path=data)
    ts = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "coldkey": "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
            "amount": "20000000000",
            "direction": "stake",
            "timestamp": ts,
            "tx_hash": f"row-{i}",
        }
        for i in range(3)
    ]
    monkeypatch.setattr(
        "internal.whales.scanner._fetch_delegation_rows",
        lambda netuid: rows,
    )
    saves = []
    with patch.object(svc, "_save_data", side_effect=lambda: saves.append(1)):
        scan_subnet_delegations(7, service=svc)
    assert len(saves) == 1
    assert len(svc.data["events"]) == 3
