"""Expert weights as a pure function of the graded ledger.

The weight for an expert depends only on its graded rows: no stored state, no
step size, no hidden history. Rows that are not graded (ungradeable, expired,
duplicate, pending) are excluded before counting. The weight is 1.0 while the
95% Wilson interval of the hit rate straddles the base rate. It moves above 1.0
only when the whole interval sits above the base rate, and below 1.0 only when
the whole interval sits below it. The result is clipped to ``[lo, hi]``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, Iterable, Optional, Tuple

GRADED_OUTCOMES = frozenset({"hit", "miss"})
Z_95 = 1.959963984540054


def wilson_interval(hits: int, n: int, z: float = Z_95) -> Tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = hits / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def eligible_rows(rows: Iterable[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    for row in rows:
        if row.get("outcome") in GRADED_OUTCOMES:
            yield row


def estimate_weights(
    rows: Iterable[Dict[str, Any]],
    *,
    base_rate: float = 0.5,
    lo: float = 0.25,
    hi: float = 2.0,
) -> Dict[str, Dict[str, Any]]:
    counts: Dict[str, list] = defaultdict(lambda: [0, 0])
    for row in eligible_rows(rows):
        key = str(row.get("expert") or "unassigned")
        counts[key][1] += 1
        counts[key][0] += row["outcome"] == "hit"
    out: Dict[str, Dict[str, Any]] = {}
    for expert, (hits, n) in sorted(counts.items()):
        lower, upper = wilson_interval(hits, n)
        if lower > base_rate:
            weight = 1.0 + (lower - base_rate) / max(1e-9, 1.0 - base_rate)
        elif upper < base_rate:
            weight = max(lo, 1.0 - (base_rate - upper) / max(1e-9, base_rate))
        else:
            weight = 1.0
        out[expert] = {
            "n": n,
            "hits": hits,
            "hit_rate": round(hits / n, 6) if n else None,
            "wilson_95": [round(lower, 6), round(upper, 6)],
            "weight": round(min(hi, max(lo, weight)), 6),
        }
    return out
