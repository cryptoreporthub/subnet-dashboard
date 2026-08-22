"""Tests for epoch-keyed daily-pick score cache (Part 2)."""

import json
import os
import time
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from internal.council import daily_pick, pick_score_cache
from internal.indicators import price_fetcher as pf
from internal.indicators import tmc_epoch


def _fake_score(sn, market_context):
    return {
        "total_score": 50.0 + float(sn["netuid"]),
        "confidence": 0.5,
        "expert_contributions": {"quant": 0.1},
        "scenario_tags": {},
    }


def _warm_tmc(epoch_unix: float) -> None:
    pf._tmc_subnets_cache["data"] = {"1": {}}
    pf._tmc_subnets_cache["cached_at"] = epoch_unix
    pf._tmc_candles_cache["data"] = {"1": {}}
    pf._tmc_candles_cache["cached_at"] = epoch_unix


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "pick_score_cache.json"
    monkeypatch.setattr(pick_score_cache, "CACHE_PATH", str(cache_path))
    monkeypatch.setattr(pick_score_cache, "LOCK_PATH", str(cache_path) + ".lock")
    pf._tmc_subnets_cache["data"] = None
    pf._tmc_subnets_cache["cached_at"] = 0.0
    pf._tmc_candles_cache["data"] = None
    pf._tmc_candles_cache["cached_at"] = 0.0
    pick_score_cache.clear_for_tests()
    yield
    pick_score_cache.clear_for_tests()


def test_tmc_data_epoch_is_min_of_both_caches():
    now = time.time()
    pf._tmc_subnets_cache["data"] = {}
    pf._tmc_subnets_cache["cached_at"] = now - 10
    pf._tmc_candles_cache["data"] = {}
    pf._tmc_candles_cache["cached_at"] = now - 5
    assert tmc_epoch.tmc_data_epoch_unix() == pytest.approx(now - 10)


def test_staleness_guard_bypasses_on_cold_epoch():
    pf._tmc_subnets_cache["data"] = None
    pf._tmc_subnets_cache["cached_at"] = 0.0
    pf._tmc_candles_cache["data"] = None
    pf._tmc_candles_cache["cached_at"] = 0.0
    assert tmc_epoch.is_epoch_stale() is True
    session = pick_score_cache.begin_session({})
    assert session["bypass"] is True
    score, status = pick_score_cache.lookup(session, 4)
    assert score is None
    assert status == "bypass_stale"


def test_staleness_guard_bypasses_on_frozen_epoch(monkeypatch):
    frozen = time.time() - 10_000
    _warm_tmc(frozen)
    monkeypatch.setattr(tmc_epoch, "DEFAULT_MAX_EPOCH_AGE_SECONDS", 60)
    assert tmc_epoch.is_epoch_stale() is True
    session = pick_score_cache.begin_session({})
    assert session["bypass"] is True
    score, status = pick_score_cache.lookup(session, 4)
    assert score is None
    assert status == "bypass_stale"


def test_hit_miss_round_trip():
    epoch = time.time()
    _warm_tmc(epoch)
    score = _fake_score({"netuid": 4}, {})
    session = pick_score_cache.begin_session({})
    assert pick_score_cache.lookup(session, 4)[1] == "miss"
    pick_score_cache.store(session, 4, score)
    pick_score_cache.end_session(session)

    session2 = pick_score_cache.begin_session({})
    cached, status = pick_score_cache.lookup(session2, 4)
    assert status == "hit"
    assert cached["total_score"] == score["total_score"]


def test_epoch_rollover_evicts_old_keys():
    epoch_a = time.time() - 30
    _warm_tmc(epoch_a)
    session = pick_score_cache.begin_session({})
    pick_score_cache.store(session, 4, _fake_score({"netuid": 4}, {}))
    pick_score_cache.end_session(session)

    epoch_b = time.time()
    _warm_tmc(epoch_b)
    session2 = pick_score_cache.begin_session({})
    cached, status = pick_score_cache.lookup(session2, 4)
    assert status == "miss"
    assert cached is None
    epochs_on_disk = pick_score_cache.list_epoch_keys()
    assert epoch_a in epochs_on_disk
    pick_score_cache.store(session2, 4, _fake_score({"netuid": 4}, {}))
    pick_score_cache.end_session(session2)
    epochs = pick_score_cache.list_epoch_keys()
    assert epoch_b in epochs


def test_entry_cap_eviction(monkeypatch):
    monkeypatch.setattr(pick_score_cache, "MAX_ENTRIES", 3)
    monkeypatch.setattr(pick_score_cache, "MAX_BYTES", 1_000_000)
    epoch = time.time()
    _warm_tmc(epoch)
    for netuid in range(5):
        session = pick_score_cache.begin_session({})
        pick_score_cache.store(session, netuid, _fake_score({"netuid": netuid}, {}))
        pick_score_cache.end_session(session)
        time.sleep(0.001)
    store = pick_score_cache._with_file_lock(pick_score_cache._load_store_unlocked)
    assert len(store["entries"]) <= 3


def test_byte_cap_eviction(monkeypatch):
    monkeypatch.setattr(pick_score_cache, "MAX_ENTRIES", 10_000)
    monkeypatch.setattr(pick_score_cache, "MAX_BYTES", 400)
    epoch = time.time()
    _warm_tmc(epoch)
    for netuid in range(8):
        session = pick_score_cache.begin_session({})
        pick_score_cache.store(
            session,
            netuid,
            _fake_score({"netuid": netuid}, {}) | {"padding": "x" * 80},
        )
        pick_score_cache.end_session(session)
    store = pick_score_cache._with_file_lock(pick_score_cache._load_store_unlocked)
    assert int(store["total_bytes"]) <= pick_score_cache.MAX_BYTES


def test_jsonl_includes_cache_field(tmp_path, monkeypatch):
    epoch = time.time()
    _warm_tmc(epoch)
    lat_path = tmp_path / "lat.jsonl"
    monkeypatch.setattr(daily_pick, "LATENCY_PATH", str(lat_path))
    subnets = [
        {"netuid": i, "name": "sn%d" % i, "symbol": "S%d" % i, "price_change_24h": 0}
        for i in range(3)
    ]

    with ExitStack() as stack:
        stack.enter_context(patch.object(daily_pick, "tradable_subnets", side_effect=lambda s: s))
        stack.enter_context(patch.object(daily_pick, "score_subnet_for_day", side_effect=_fake_score))
        stack.enter_context(
            patch.object(
                daily_pick,
                "audit_daily_pick",
                side_effect=lambda c, s: {"approved": True, "adjusted_confidence": 0.5},
            )
        )
        stack.enter_context(patch.object(daily_pick, "attach_council_prediction", return_value={}))
        stack.enter_context(patch.object(daily_pick, "pick_reasons", return_value=[]))
        stack.enter_context(
            patch.object(
                daily_pick,
                "unpack_score_learning_fields",
                return_value={
                    "signal_impact": None,
                    "signal_contributions": None,
                    "active_signals": [],
                },
            )
        )
        stack.enter_context(
            patch("internal.indicators.tmc_singleflight.install_once", return_value=None)
        )
        stack.enter_context(
            patch("internal.indicators.tmc_singleflight.prewarm", return_value=True)
        )
        # First pick: all miss
        daily_pick.select_daily_pick(subnets, {})
        rows1 = [json.loads(l) for l in lat_path.read_text().strip().splitlines()]
        assert all(r.get("cache") == "miss" for r in rows1)
        assert all("epoch_unix" in r for r in rows1)

        # Second pick same epoch: all hit
        daily_pick.select_daily_pick(subnets, {})
        rows2 = [json.loads(l) for l in lat_path.read_text().strip().splitlines()][-3:]
        assert all(r.get("cache") == "hit" for r in rows2)


def test_frozen_epoch_source_yields_zero_hits_in_select(tmp_path, monkeypatch):
    # Seed disk while TMC epoch is fresh (would hit if staleness guard were absent).
    epoch_fresh = time.time()
    _warm_tmc(epoch_fresh)
    session = pick_score_cache.begin_session({})
    pick_score_cache.store(session, 1, _fake_score({"netuid": 1}, {}))
    pick_score_cache.end_session(session)

    frozen = time.time() - 10_000
    _warm_tmc(frozen)
    monkeypatch.setattr(tmc_epoch, "DEFAULT_MAX_EPOCH_AGE_SECONDS", 60)
    lat_path = tmp_path / "lat.jsonl"
    monkeypatch.setattr(daily_pick, "LATENCY_PATH", str(lat_path))
    subnets = [{"netuid": 1, "name": "A", "symbol": "S1", "price_change_24h": 0}]
    calls = {"n": 0}

    def counting_score(sn, ctx):
        calls["n"] += 1
        return _fake_score(sn, ctx)

    with ExitStack() as stack:
        stack.enter_context(patch.object(daily_pick, "tradable_subnets", side_effect=lambda s: s))
        stack.enter_context(patch.object(daily_pick, "score_subnet_for_day", side_effect=counting_score))
        stack.enter_context(
            patch.object(
                daily_pick,
                "audit_daily_pick",
                side_effect=lambda c, s: {"approved": True, "adjusted_confidence": 0.5},
            )
        )
        stack.enter_context(patch.object(daily_pick, "attach_council_prediction", return_value={}))
        stack.enter_context(patch.object(daily_pick, "pick_reasons", return_value=[]))
        stack.enter_context(
            patch.object(
                daily_pick,
                "unpack_score_learning_fields",
                return_value={
                    "signal_impact": None,
                    "signal_contributions": None,
                    "active_signals": [],
                },
            )
        )
        stack.enter_context(
            patch("internal.indicators.tmc_singleflight.install_once", return_value=None)
        )
        stack.enter_context(
            patch("internal.indicators.tmc_singleflight.prewarm", return_value=True)
        )
        daily_pick.select_daily_pick(subnets, {})

    rows = [json.loads(l) for l in lat_path.read_text().strip().splitlines()]
    assert rows[0]["cache"] == "bypass_stale"
    assert calls["n"] == 1
