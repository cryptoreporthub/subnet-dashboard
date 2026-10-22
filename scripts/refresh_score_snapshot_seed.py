#!/usr/bin/env python3
"""Copy or build a complete score snapshot into data_seeds/ (#1479 PR-B)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from internal.chain_price.membership import read_chain_membership  # noqa: E402
from internal.chain_price.reader import ChainReader  # noqa: E402
from internal.council.build_seed_snapshot import build_image_seed_snapshot  # noqa: E402
from internal.council.seed_market_inputs import refresh_committed_authoritative_rows  # noqa: E402
from internal.council.score_snapshots import is_complete_snapshot, publish_complete_snapshot  # noqa: E402
from internal.council.seed_quality import validate_shipped_seed  # noqa: E402


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
    parser.add_argument(
        "--build",
        action="store_true",
        help="Read membership from the chain and run the real scorer build into --dest (ignores source path)",
    )
    args = parser.parse_args()
    if args.build:
        chain, outcome = read_chain_membership(ChainReader())
        if chain is None:
            print(f"chain membership read failed: {outcome}", file=sys.stderr)
            return 2
        try:
            refresh_committed_authoritative_rows(chain.netuids)
        except (OSError, ValueError) as exc:
            print(f"WARN: could not refresh authoritative_universe_rows: {exc}", file=sys.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            volume = os.path.join(tmp, "build.json")
            cycle = os.path.join(tmp, "cycle.json")
            out = build_image_seed_snapshot(chain=chain, volume_path=volume, cycle_path=cycle)
            if not out.get("published"):
                print(f"build failed: {out}", file=sys.stderr)
                return 2
            with open(volume, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
    else:
        with open(args.source, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    if not isinstance(payload, dict):
        print("source is not a JSON object", file=sys.stderr)
        return 2
    if not is_complete_snapshot(payload):
        print("source fails is_complete_snapshot — refusing to refresh seed", file=sys.stderr)
        return 2
    ok, reason = validate_shipped_seed(payload)
    if not ok:
        print(f"seed fails validate_shipped_seed ({reason})", file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(args.dest) or ".", exist_ok=True)
    result = publish_complete_snapshot(payload, args.dest)
    if not result.get("published"):
        print(f"seed write refused: {result}", file=sys.stderr)
        return 2
    print(f"seed refreshed at {args.dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
