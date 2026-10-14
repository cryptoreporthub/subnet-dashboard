"""Step 3 backfill scaffold + bracketed resolve (#1395)."""

from __future__ import annotations

import pytest

from internal.chain_price.backfill import plan_hourly_bucket_ts_ms, run_backfill_dry_run
from internal.chain_price.block_resolve import clear_block_cache, resolve_block_at
from tests.test_block_resolve_convergence_1406 import HEAD, WINDOW, _SyntheticChain


def test_plan_hourly_bucket_count_30d():
    end = 1_700_000_000_000
    buckets = plan_hourly_bucket_ts_ms(end, days=30)
    assert len(buckets) == 30 * 24
    assert buckets[0] < buckets[-1] <= end


def test_backfill_dry_run_payload():
    out = run_backfill_dry_run(1_700_000_000_000, search="bracketed")
    assert out["outcome"] == "dry_run"
    assert out["search"] == "bracketed"


def test_bracketed_resolves_case_that_exhausts_stepped():
    """seed=6 / jitter=3000 exhausts stepped search in one synthetic case."""
    from tests.test_block_resolve_convergence_1406 import _SyntheticChain

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
    """Default bracketed budget must not fail where stepped succeeds (Claude #1411)."""
    for seed in range(16):
        for jitter in (1000, 3000):
            chain = _SyntheticChain(seed=seed, jitter=jitter)
            for target in range(HEAD - WINDOW, HEAD, 512):
                ts_ms = chain.ts[target] + 2_000
                clear_block_cache()
                stepped = resolve_block_at(chain, ts_ms, search="stepped")
                if stepped[2] != "ok":
                    continue
                clear_block_cache()
                bracketed = resolve_block_at(chain, ts_ms, search="bracketed")
                assert bracketed[2] == "ok", (seed, jitter, target)


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
