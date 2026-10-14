#!/usr/bin/env python3
"""One-shot historical chain price backfill (#1395 Step 3). RPC + DB writes land in follow-up slices."""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from internal.chain_price.backfill import plan_hourly_bucket_ts_ms, run_backfill_dry_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan or run chain_sampled historical backfill")
    parser.add_argument("--days", type=int, default=30, help="Lookback days (hourly buckets)")
    parser.add_argument("--dry-run", action="store_true", help="Print bucket plan only")
    parser.add_argument("--max-buckets", type=int, default=0, help="Limit buckets (0 = all)")
    parser.add_argument(
        "--search",
        choices=("stepped", "bracketed"),
        default="bracketed",
        help="resolve_block_at search mode for buckets",
    )
    args = parser.parse_args(argv)

    buckets = plan_hourly_bucket_ts_ms(days=args.days)
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

    print("Live backfill not implemented in this scaffold; use --dry-run.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
