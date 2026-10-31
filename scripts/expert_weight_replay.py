"""Replay expert weights over a resolved-predictions dump and print a base-rate sweep.

Usage: python scripts/expert_weight_replay.py <resolved.json> [base_rate ...]
The dump is the body of GET /api/predictions/resolved (read-only).
"""

import json
import sys

from internal.learning.expert_weights import estimate_weights


def main(argv):
    rows = json.load(open(argv[1]))["resolved"]
    bases = [float(x) for x in argv[2:]] or [0.40, 0.45, 0.50]
    for base in bases:
        print(f"base_rate={base:.2f}")
        for expert, stats in estimate_weights(rows, base_rate=base).items():
            lo, hi = stats["wilson_95"]
            print(f"  {expert:10s} n={stats['n']:4d} hit={stats['hit_rate']:.3f} "
                  f"wilson=[{lo:.3f},{hi:.3f}] weight={stats['weight']:.3f}")


if __name__ == "__main__":
    main(sys.argv)
