#!/usr/bin/env python3
"""Reset Telegram / message-intel store for a clean desk epoch.

Examples:
  # Start fresh from yesterday (UTC) — week panels may be quiet until more data lands
  python scripts/reset_message_intel.py --since-yesterday --clean-alerts

  # Keep 7 days — preserves comment-of-week / champions / yesterday leader rollups
  python scripts/reset_message_intel.py --keep-week --clean-alerts

  # Full wipe (listener re-ingests; week panels empty until data returns)
  python scripts/reset_message_intel.py --full --clean-alerts

  # Preview counts only
  python scripts/reset_message_intel.py --since-yesterday --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys

from internal.message_intel.reset_store import reset_message_intel


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset message-intel / Telegram desk data")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--since-yesterday",
        action="store_true",
        help="Delete messages before start of yesterday UTC (keep yesterday + today)",
    )
    group.add_argument(
        "--keep-week",
        action="store_true",
        help="Delete messages older than 7 days (keeps week desk panels populated)",
    )
    group.add_argument(
        "--full",
        action="store_true",
        help="Wipe message_intel.db entirely and recreate schema",
    )
    parser.add_argument(
        "--keep-days",
        type=int,
        default=7,
        help="With --keep-week, number of days to retain (default 7)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count only; no deletes")
    parser.add_argument(
        "--clean-alerts",
        action="store_true",
        help="Remove social_intel rows from data/alerts.json",
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        default=None,
        help="Override MESSAGE_INTEL_DB path",
    )
    args = parser.parse_args()

    if args.full:
        mode = "full"
    elif args.keep_week:
        mode = "week"
    else:
        mode = "yesterday"

    summary = reset_message_intel(
        mode=mode,
        keep_days=args.keep_days,
        dry_run=args.dry_run,
        clean_alerts=args.clean_alerts,
        db_path=args.db_path,
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
