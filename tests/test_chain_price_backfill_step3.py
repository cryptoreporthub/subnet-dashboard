"""Step 3 backfill scaffold + bracketed resolve (#1395)."""

from __future__ import annotations

from internal.chain_price.backfill import plan_hourly_bucket_ts_ms, run_backfill_dry_run
from internal.chain_price.block_resolve import clear_block_cache, resolve_block_at


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
