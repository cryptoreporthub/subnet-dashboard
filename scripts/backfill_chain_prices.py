#!/usr/bin/env python3
"""One-shot historical chain price backfill (#1395 Step 3)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from internal.chain_price.backfill import (
    backfill_bucket,
    backfill_sleep_seconds,
    plan_hourly_bucket_ts_ms,
    run_backfill_dry_run,
)
from internal.chain_price.config import rpc_provider_clients
from internal.chain_price.reader import ChainReader


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan or run chain_sampled historical backfill")
    parser.add_argument("--days", type=int, default=30, help="Lookback days (hourly buckets)")
    parser.add_argument("--dry-run", action="store_true", help="Plan buckets only (no RPC/DB writes)")
    parser.add_argument(
        "--db-path",
        default=os.environ.get("CHAIN_PRICE_DB_PATH", "data/chain_prices.db"),
        help="SQLite path for chain_prices.db",
    )
    parser.add_argument("--end-ts", type=int, default=0, help="End timestamp ms (0 = now)")
    parser.add_argument("--max-buckets", type=int, default=0, help="Limit buckets (0 = all)")
    parser.add_argument(
        "--search",
        choices=("stepped", "bracketed"),
        default="bracketed",
        help="resolve_block_at search mode for buckets",
    )
    args = parser.parse_args(argv)

    end_ms = args.end_ts if args.end_ts > 0 else None
    buckets = plan_hourly_bucket_ts_ms(end_ms, days=args.days)
    if args.max_buckets > 0:
        buckets = buckets[-args.max_buckets :]

    if args.dry_run:
        payload = {
            "days": args.days,
            "bucket_count": len(buckets),
            "first_bucket_ts_ms": buckets[0] if buckets else None,
            "last_bucket_ts_ms": buckets[-1] if buckets else None,
            "search": args.search,
            "samples": [run_backfill_dry_run(b, search=args.search) for b in buckets[:3]],
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    reader = ChainReader(rpc_provider_clients())
    results = []
    sleep_s = backfill_sleep_seconds()
    for idx, bucket_ts in enumerate(buckets):
        results.append(
            backfill_bucket(
                reader,
                bucket_ts,
                db_path=args.db_path,
                dry_run=False,
                gecko_fallback=False,
                search=args.search,
            )
        )
        if idx + 1 < len(buckets) and sleep_s > 0:
            time.sleep(sleep_s)

    json.dump({"bucket_count": len(buckets), "results": results}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    failed = [r for r in results if r.get("outcome") not in ("ok", "skipped")]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
