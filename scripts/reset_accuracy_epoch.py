#!/usr/bin/env python3
"""Archive predictions.json and start a fresh accuracy epoch (Acc-0)."""

from __future__ import annotations

import argparse
import json
import sys

from internal.learning.ledger_heal import archive_predictions_epoch


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive predictions and reset accuracy epoch")
    parser.add_argument(
        "--no-heal",
        action="store_true",
        help="Skip daily-pick ledger backfill after reset",
    )
    args = parser.parse_args()
    summary = archive_predictions_epoch(re_heal_daily=not args.no_heal)
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
