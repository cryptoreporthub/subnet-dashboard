#!/usr/bin/env python3
"""One-time soft reblend of council expert weights after the Rogue attribution fix.

Mean-reverts each expert weight toward the 1.0 prior by 50% (w' = 1 + 0.5*(w-1)),
clamped to [0.1, 2.0], emits weight_change trail rows, and reports how many
replay rows the Rogue guard now keeps out of real-expert weight nudges.

Quant was pinned at the 2.0 cap because the legacy fallback credited unresolved
rows to quant; after fixing attribution this pass pulls it back (2.00 -> 1.50)
without erasing genuinely earned weight.

Usage:
    python scripts/rebalance_expert_weights.py --dry-run   # preview only
    python scripts/rebalance_expert_weights.py --save      # persist + trail
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict


def mean_revert(weights: Dict[str, float], share: float = 0.5) -> Dict[str, float]:
    """w' = 1 + share*(w-1), clamped to the same [0.1, 2.0] band as the learner."""
    lo, hi = 0.1, 2.0
    return {
        name: round(max(lo, min(hi, 1.0 + share * (float(weights.get(name, 1.0)) - 1.0))), 4)
        for name in ("quant", "hype", "dark_horse", "technical")
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="print before/after, change nothing")
    group.add_argument("--save", action="store_true", help="persist weights + emit trail rows")
    args = parser.parse_args()

    from internal.council.weights import SOUL_MAP_PATH, load_weights, save_weights
    from internal.learning.trail_bus import emit_weight_change
    from internal.learning.weight_deltas import count_rogue_replay_rows

    before = load_weights(SOUL_MAP_PATH) or {}
    after = mean_revert(before)

    rogue = count_rogue_replay_rows()

    print("Rogue replay guard (fix 3):", rogue)
    print(f"{'expert':<12} {'before':>8} {'after':>8}")
    for name in ("quant", "hype", "dark_horse", "technical"):
        print(f"{name:<12} {float(before.get(name, 1.0)):>8.4f} {after[name]:>8.4f}")

    if args.dry_run:
        print("[dry-run] no changes persisted.")
        return 0

    save_weights(after, SOUL_MAP_PATH)
    for name in ("quant", "hype", "dark_horse", "technical"):
        b = float(before.get(name, 1.0))
        if abs(after[name] - b) > 0.001:
            emit_weight_change(
                name,
                before=b,
                after=after[name],
                reason="rogue_rebalance_attribution_fix",
            )
    print("[saved] weights persisted + trail rows emitted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
