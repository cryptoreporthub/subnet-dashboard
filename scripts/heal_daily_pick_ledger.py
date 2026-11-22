#!/usr/bin/env python3
"""Ops helper — heal today's daily-pick ledger gap (Acc-0)."""

from __future__ import annotations

import argparse
import json
import sys

from internal.learning.ledger_heal import heal_daily_pick_ledger


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill missing day ledger row for today's LONG")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write heal (default is dry-run)",
    )
    args = parser.parse_args()
    summary = heal_daily_pick_ledger(dry_run=not args.apply)
    print(json.dumps(summary, indent=2))
    if not summary.get("ok"):
        return 1
    if summary.get("healed") or summary.get("reason") in ("ledger_present", "no_published_long"):
        return 0
    if summary.get("dry_run"):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
