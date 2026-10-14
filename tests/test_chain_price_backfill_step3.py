"""Step 3 backfill scaffold + bracketed resolve (#1395)."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from internal.chain_price import config as chain_cfg
from internal.chain_price.backfill import (
    backfill_bucket,
    plan_hourly_bucket_ts_ms,
    run_backfill_dry_run,
    validate_backfill_days,
)
from internal.chain_price.block_resolve import clear_block_cache, resolve_block_at
from internal.chain_price.reader import ChainReader
from tests.test_block_resolve_convergence_1406 import HEAD, WINDOW, _SyntheticChain
from tests.test_chain_price_step2 import PINNED_HASH, fixture_client

# Claude review grid: 16 seeds × 2 jitters × 1_200 targets (step 417) = 38_400 cases.
_SYNTHETIC_SWEEP_STEP = 417


def test_plan_hourly_bucket_count_30d():
    end = 1_700_000_000_000
    buckets = plan_hourly_bucket_ts_ms(end, days=30)
    assert len(buckets) == 30 * 24
    assert buckets[0] < buckets[-1] <= end


def test_backfill_dry_run_payload():
    out = run_backfill_dry_run(1_700_000_000_000, search="bracketed")
    assert out["outcome"] == "dry_run"
    assert out["search"] == "bracketed"
    assert "note" in out


def test_backfill_rerun_skips_when_block_ts_precedes_bucket(fixture_client, tmp_path):
    """A block stamped up to 12s before the hour is accepted for that bucket and must still be skipped on rerun."""
    client, _ = fixture_client
    db_path = str(tmp_path / "chain_prices.db")
    reader = ChainReader([("blockmachine", client)])
    block_ts_ms = 1_789_328_964_000
    bucket_ts_ms = block_ts_ms + 5_000  # sample ts lands 5s before bucket start

    with patch(
        "internal.chain_price.backfill.resolve_block_at",
        return_value=(9_060_887, PINNED_HASH, "ok"),
    ):
        first = backfill_bucket(reader, bucket_ts_ms, db_path=db_path, search="bracketed")
        second = backfill_bucket(reader, bucket_ts_ms, db_path=db_path, search="bracketed")

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM chain_price_samples").fetchone()[0]
    conn.close()
    assert first["outcome"] == "ok"
    assert first["samples_written"] > 0
    assert second["outcome"] == "skipped"
    assert count == first["samples_written"]


def test_backfill_bucket_writes_and_idempotent(fixture_client, tmp_path):
    client, _ = fixture_client
    db_path = str(tmp_path / "chain_prices.db")
    reader = ChainReader([("blockmachine", client)])
    bucket_ts_ms = (1_789_328_964_000 // 3_600_000) * 3_600_000

    with patch(
        "internal.chain_price.backfill.resolve_block_at",
        return_value=(9_060_887, PINNED_HASH, "ok"),
    ):
        first = backfill_bucket(reader, bucket_ts_ms, db_path=db_path, search="bracketed")
        second = backfill_bucket(reader, bucket_ts_ms, db_path=db_path, search="bracketed")

    assert first["outcome"] == "ok"
    assert first["samples_written"] > 0
    assert second["outcome"] == "skipped"
    assert second["samples_written"] == 0

    conn = sqlite3.connect(db_path)
    kind = conn.execute("SELECT kind FROM chain_blocks LIMIT 1").fetchone()[0]
    count = conn.execute("SELECT COUNT(*) FROM chain_price_samples").fetchone()[0]
    conn.close()
    assert kind == "backfill"
    assert count == first["samples_written"]


def test_backfill_dry_run_unknown_search_raises():
    with pytest.raises(ValueError, match="unknown search"):
        run_backfill_dry_run(1_700_000_000_000, search="bogus")


def test_backfill_function_dry_run_does_not_create_db(fixture_client, tmp_path):
    client, _ = fixture_client
    db_path = str(tmp_path / "chain_prices.db")
    reader = ChainReader([("blockmachine", client)])
    bucket_ts_ms = (1_789_328_964_000 // 3_600_000) * 3_600_000
    with patch(
        "internal.chain_price.backfill.resolve_block_at",
        return_value=(9_060_887, PINNED_HASH, "ok"),
    ):
        out = backfill_bucket(reader, bucket_ts_ms, db_path=db_path, dry_run=True, search="bracketed")
    assert out["outcome"] == "dry_run"
    assert not (tmp_path / "chain_prices.db").exists()


def test_validate_backfill_days_hard_cap():
    validate_backfill_days(chain_cfg.BACKFILL_MAX_DAYS)
    with pytest.raises(ValueError, match="exceeds hard cap"):
        validate_backfill_days(chain_cfg.BACKFILL_MAX_DAYS + 1)


def test_backfill_disk_guard_blocks_writes(fixture_client, tmp_path):
    client, _ = fixture_client
    db_path = str(tmp_path / "chain_prices.db")
    reader = ChainReader([("blockmachine", client)])
    bucket_ts_ms = (1_789_328_964_000 // 3_600_000) * 3_600_000
    with patch(
        "internal.disk_guard.db_disk_guard_outcome",
        return_value="disk_low",
    ):
        out = backfill_bucket(reader, bucket_ts_ms, db_path=db_path, search="bracketed")
    assert out["outcome"] == "disk_low"
    assert not (tmp_path / "chain_prices.db").exists()


def test_row_cap_near_full_batch_rejected_not_false_ok(fixture_client, tmp_path):
    """ROW_CAP=3 with two rows: a full subnet batch must fail closed, not ok after prune."""
    from internal.chain_price import db as price_db

    client, _ = fixture_client
    db_path = str(tmp_path / "chain_prices.db")
    price_db.ensure_schema(db_path)
    filler = [
        {
            "netuid": i,
            "block": 1,
            "provider": "blockmachine",
            "ts_ms": 1_600_000_000_000 + i,
            "registered_at": 1,
            "tao_reserve_raw": 1,
            "alpha_reserve_raw": 1,
            "price_tao": 1.0,
            "spot_price_tao": None,
            "unit": "tao",
            "quality": "chain_sampled",
            "schema_version": chain_cfg.SCHEMA_VERSION,
        }
        for i in range(2)
    ]
    reader = ChainReader([("blockmachine", client)])
    bucket_ts_ms = (1_789_328_964_000 // 3_600_000) * 3_600_000
    with patch.object(price_db, "ROW_CAP", 3):
        price_db.insert_sample_rows(filler, path=db_path)
        with patch(
            "internal.chain_price.backfill.resolve_block_at",
            return_value=(9_060_887, PINNED_HASH, "ok"),
        ):
            out = backfill_bucket(reader, bucket_ts_ms, db_path=db_path, search="bracketed")
    assert out["outcome"] == "row_cap_exceeded"
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM chain_price_samples").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM chain_blocks").fetchone()[0] == 0
    conn.close()


def test_hourly_bucket_skip_requires_distinct_netuids_not_duplicate_providers(tmp_path):
    from internal.chain_price import db as price_db

    db_path = str(tmp_path / "chain_prices.db")
    price_db.ensure_schema(db_path)
    bucket_ts_ms = 1_700_000_000_000
    block = 42
    n_subnets = 3
    price_db.insert_block_row(
        provider="a",
        block=block,
        block_hash="0xabc",
        ts_ms=bucket_ts_ms,
        bucket_ts=bucket_ts_ms,
        kind="backfill",
        n_subnets=n_subnets,
        path=db_path,
    )
    rows = [
        {
            "netuid": 1,
            "block": block,
            "provider": "p1",
            "ts_ms": bucket_ts_ms,
            "registered_at": 1,
            "tao_reserve_raw": 1,
            "alpha_reserve_raw": 1,
            "price_tao": 1.0,
            "spot_price_tao": None,
            "unit": "tao",
            "quality": "chain_sampled",
            "schema_version": chain_cfg.SCHEMA_VERSION,
        },
        {
            "netuid": 1,
            "block": block,
            "provider": "p2",
            "ts_ms": bucket_ts_ms,
            "registered_at": 1,
            "tao_reserve_raw": 1,
            "alpha_reserve_raw": 1,
            "price_tao": 1.0,
            "spot_price_tao": None,
            "unit": "tao",
            "quality": "chain_sampled",
            "schema_version": chain_cfg.SCHEMA_VERSION,
        },
    ]
    price_db.insert_sample_rows(rows, path=db_path)
    assert not price_db.hourly_bucket_has_chain_sample(bucket_ts_ms, path=db_path)


def test_neighboring_hour_forward_sample_does_not_skip_backfill_bucket(fixture_client, tmp_path):
    from internal.chain_price import db as price_db

    client, _ = fixture_client
    db_path = str(tmp_path / "chain_prices.db")
    price_db.ensure_schema(db_path)
    bucket_ts_ms = (1_789_328_964_000 // 3_600_000) * 3_600_000
    neighbor_ts = bucket_ts_ms - 3_600_000
    price_db.insert_block_row(
        provider="blockmachine",
        block=9_060_000,
        block_hash="0xneighbor",
        ts_ms=neighbor_ts,
        bucket_ts=neighbor_ts,
        kind="forward",
        n_subnets=128,
        path=db_path,
    )
    price_db.insert_sample_rows(
        [
            {
                "netuid": 1,
                "block": 9_060_000,
                "provider": "blockmachine",
                "ts_ms": neighbor_ts,
                "registered_at": 1,
                "tao_reserve_raw": 1,
                "alpha_reserve_raw": 1,
                "price_tao": 1.0,
                "spot_price_tao": None,
                "unit": "tao",
                "quality": "chain_sampled",
                "schema_version": chain_cfg.SCHEMA_VERSION,
            }
        ],
        path=db_path,
    )
    assert not price_db.hourly_bucket_has_chain_sample(bucket_ts_ms, path=db_path)
    reader = ChainReader([("blockmachine", client)])
    with patch(
        "internal.chain_price.backfill.resolve_block_at",
        return_value=(9_060_887, PINNED_HASH, "ok"),
    ):
        out = backfill_bucket(reader, bucket_ts_ms, db_path=db_path, search="bracketed")
    assert out["outcome"] == "ok"


def test_backfill_zero_byte_db_does_not_crash_on_skip_check(fixture_client, tmp_path):
    client, _ = fixture_client
    db_path = str(tmp_path / "chain_prices.db")
    (tmp_path / "chain_prices.db").write_bytes(b"")
    reader = ChainReader([("blockmachine", client)])
    bucket_ts_ms = (1_789_328_964_000 // 3_600_000) * 3_600_000
    with patch(
        "internal.chain_price.backfill.resolve_block_at",
        return_value=(9_060_887, PINNED_HASH, "ok"),
    ):
        out = backfill_bucket(reader, bucket_ts_ms, db_path=db_path, search="bracketed")
    assert out["outcome"] == "ok"


def test_backfill_row_cap_blocks_writes(fixture_client, tmp_path):
    from internal.chain_price import db as price_db

    client, _ = fixture_client
    db_path = str(tmp_path / "chain_prices.db")
    price_db.ensure_schema(db_path)
    rows = [
        {
            "netuid": i,
            "block": 1,
            "provider": "blockmachine",
            "ts_ms": 1_700_000_000_000 + i,
            "registered_at": 1,
            "tao_reserve_raw": 1,
            "alpha_reserve_raw": 1,
            "price_tao": 1.0,
            "spot_price_tao": None,
            "unit": "tao",
            "quality": "chain_sampled",
            "schema_version": chain_cfg.SCHEMA_VERSION,
        }
        for i in range(2)
    ]
    with patch.object(price_db, "ROW_CAP", 2):
        price_db.insert_sample_rows(rows, path=db_path)
        reader = ChainReader([("blockmachine", client)])
        bucket_ts_ms = (1_789_328_964_000 // 3_600_000) * 3_600_000
        with patch(
            "internal.chain_price.backfill.resolve_block_at",
            return_value=(9_060_887, PINNED_HASH, "ok"),
        ):
            out = backfill_bucket(reader, bucket_ts_ms, db_path=db_path, search="bracketed")
    assert out["outcome"] == "row_cap_exceeded"
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM chain_price_samples").fetchone()[0] == 2
    conn.close()


def test_bracketed_resolve_rpc_budget_regression():
    """Resolver-only RPC calls per bucket must stay within the documented synthetic ceiling."""
    max_calls = 0
    step = 417
    for seed in range(16):
        for jitter in (1000, 3000):
            chain = _SyntheticChain(seed=seed, jitter=jitter)
            orig_call = chain.call

            for target in range(HEAD - WINDOW, HEAD, step):
                calls = {"n": 0}

                def counted_call(method, params):
                    calls["n"] += 1
                    return orig_call(method, params)

                chain.call = counted_call
                clear_block_cache()
                resolve_block_at(chain, chain.ts[target] + 2_000, search="bracketed")
                chain.call = orig_call
                max_calls = max(max_calls, calls["n"])
    assert max_calls <= chain_cfg.BRACKETED_RESOLVE_RPC_BUDGET_PER_BUCKET


def test_bracketed_resolves_case_that_exhausts_stepped():
    """seed=6 / jitter=3000 exhausts stepped search in one synthetic case."""
    clear_block_cache()
    chain = _SyntheticChain(seed=6, jitter=3000)
    target = 9_081_136
    ts_ms = chain.ts[target] + 2_000
    stepped = resolve_block_at(chain, ts_ms, search="stepped")
    bracketed = resolve_block_at(chain, ts_ms, search="bracketed")
    assert stepped[2] == "invalid"
    assert bracketed[2] == "ok"
    assert abs(bracketed[0] - target) <= 1


def test_bracketed_ok_whenever_stepped_ok_on_synthetic_sweep():
    """Default bracketed budget must not fail where stepped succeeds (Claude #1411, 38_400 grid)."""
    failures = []
    for seed in range(16):
        for jitter in (1000, 3000):
            chain = _SyntheticChain(seed=seed, jitter=jitter)
            for target in range(HEAD - WINDOW, HEAD, _SYNTHETIC_SWEEP_STEP):
                ts_ms = chain.ts[target] + 2_000
                clear_block_cache()
                stepped = resolve_block_at(chain, ts_ms, search="stepped")
                if stepped[2] != "ok":
                    continue
                clear_block_cache()
                bracketed = resolve_block_at(chain, ts_ms, search="bracketed")
                if bracketed[2] != "ok":
                    failures.append((seed, jitter, target))
    assert failures == []


def test_stepped_warm_exact_hint_returns_pair_with_zero_reader_calls():
    """Repeat same ts+hint on default stepped path must hit exact-hint cache (Replit #1411 P2)."""
    chain = _SyntheticChain(seed=7, jitter=1000)
    target = HEAD - 123_456
    ts_ms = chain.ts[target] + 2_000
    hint = target

    clear_block_cache()
    warm = resolve_block_at(chain, ts_ms, hint_block=hint)
    assert warm[2] == "ok"
    assert abs(warm[0] - target) <= 1

    calls = {"n": 0}
    orig_call = chain.call

    def counted_call(method, params):
        calls["n"] += 1
        return orig_call(method, params)

    chain.call = counted_call
    repeat = resolve_block_at(chain, ts_ms, hint_block=hint)
    assert repeat == warm
    assert calls["n"] == 0


def test_stepped_unchanged_when_block_cache_warm_from_bracketed():
    chain = _SyntheticChain(seed=7, jitter=1000)
    target_a, target_b = HEAD - 50_000, HEAD - 120_000
    ts_a, ts_b = chain.ts[target_a] + 2_000, chain.ts[target_b] + 2_000

    clear_block_cache()
    resolve_block_at(chain, ts_a, search="bracketed")
    warm = resolve_block_at(chain, ts_b, search="stepped")

    clear_block_cache()
    cold = resolve_block_at(chain, ts_b, search="stepped")

    assert warm == cold


def test_unknown_search_raises():
    chain = _SyntheticChain()
    with pytest.raises(ValueError, match="unknown search"):
        resolve_block_at(chain, chain.ts[HEAD - 1000], search="bisect")
