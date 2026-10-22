#!/usr/bin/env python3
"""Copy a complete score snapshot into data_seeds/ for image ship (#1479 PR-B)."""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from internal.council.score_snapshots import is_complete_snapshot, save_score_snapshot  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        nargs="?",
        default=os.path.join("data", "score_snapshots.json"),
        help="Complete snapshot JSON to copy into the image seed",
    )
    parser.add_argument(
        "--dest",
        default=os.path.join("data_seeds", "score_snapshots.json"),
        help="Seed path (default: data_seeds/score_snapshots.json)",
    )
    args = parser.parse_args()
    with open(args.source, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        print("source is not a JSON object", file=sys.stderr)
        return 2
    if not is_complete_snapshot(payload):
        print("source fails is_complete_snapshot — refusing to refresh seed", file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(args.dest) or ".", exist_ok=True)
    result = save_score_snapshot(payload, args.dest)
    if not result.get("published"):
        print(f"seed write refused: {result}", file=sys.stderr)
        return 2
    print(f"seed refreshed at {args.dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
