"""Step 3 backfill scaffold + bracketed resolve (#1395)."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from internal.chain_price.backfill import backfill_bucket, plan_hourly_bucket_ts_ms, run_backfill_dry_run
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
