#!/usr/bin/env python3
"""Read-only impact report for #1375 integrity (gradeable cache + unit guard).

Usage:
  PYTHONPATH=. python scripts/issue_1375_integrity_impact.py
  PYTHONPATH=. python scripts/issue_1375_integrity_impact.py --predictions /path/to/predictions.json
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, Iterable, List, Tuple

from internal.council.grading import PRICE_UNIT_RATIO_CEILING, is_price_unit_mismatch
from internal.council.price_reference import (
    is_derived_candle_cache_source,
    refuse_derived_for_grading_enabled,
)

DEFAULT_CACHE = os.path.join("data", "price_cache.json")
DEFAULT_PREDICTIONS = os.path.join("data", "predictions.json")


def _legacy_price_unit_mismatch(reference_price: float, resolved_price: float) -> bool:
    """Pre-#1377 guard (main): exempt ratio>=20 when min(ref, resolved) >= 1."""
    try:
        reference = float(reference_price)
        resolved = float(resolved_price)
    except (TypeError, ValueError):
        return False
    if reference <= 0 or resolved <= 0:
        return False
    ratio = max(reference, resolved) / min(reference, resolved)
    if min(reference, resolved) >= 1:
        return False
    return ratio >= PRICE_UNIT_RATIO_CEILING


def subnets_with_any_candles(cache: Dict[str, Any]) -> int:
    """Cache blocks with at least one candle row (ignores derived-source policy)."""
    count = 0
    for block in cache.values():
        if not isinstance(block, dict):
            continue
        candles = [c for c in (block.get("candles") or []) if isinstance(c, dict)]
        if candles:
            count += 1
    return count


def gradeable_subnet_counts(
    cache: Dict[str, Any], *, refuse_derived: bool
) -> int:
    """Subnets with non-empty candles that remain gradeable under *refuse_derived*."""
    count = 0
    for block in cache.values():
        if not isinstance(block, dict):
            continue
        candles = [c for c in (block.get("candles") or []) if isinstance(c, dict)]
        if not candles:
            continue
        if refuse_derived and is_derived_candle_cache_source(block.get("source")):
            continue
        count += 1
    return count


def _iter_resolved_rows(path: str) -> Iterable[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError:
        return []
    rows = data.get("resolved") or []
    return [r for r in rows if isinstance(r, dict)]


def learning_export_guard_counts(rows: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    row_list = list(rows)
    both_ge1_ratio20 = 0
    newly_flagged = 0
    phantom_sub1 = 0
    for row in row_list:
        ref = row.get("reference_price")
        res = row.get("resolved_price")
        try:
            reference = float(ref)
            resolved = float(res)
        except (TypeError, ValueError):
            continue
        if reference <= 0 or resolved <= 0:
            continue
        ratio = max(reference, resolved) / min(reference, resolved)
        if reference >= 1 and resolved >= 1 and ratio >= PRICE_UNIT_RATIO_CEILING:
            both_ge1_ratio20 += 1
        if is_price_unit_mismatch(reference, resolved) and not _legacy_price_unit_mismatch(
            reference, resolved
        ):
            newly_flagged += 1
        if (
            reference < 1
            and resolved < 1
            and is_price_unit_mismatch(reference, resolved)
        ):
            phantom_sub1 += 1
    return {
        "resolved_rows": len(row_list),
        "both_ge1_ratio20": both_ge1_ratio20,
        "newly_flagged_by_unit_guard": newly_flagged,
        "phantom_sub1_still_flagged": phantom_sub1,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", default=DEFAULT_CACHE)
    parser.add_argument("--predictions", default=DEFAULT_PREDICTIONS)
    args = parser.parse_args()

    with open(args.cache, "r", encoding="utf-8") as fh:
        cache = json.load(fh)

    any_candles = subnets_with_any_candles(cache)

    prev_refuse = os.environ.get("REFUSE_DERIVED_FOR_GRADING")
    os.environ.pop("REFUSE_DERIVED_FOR_GRADING", None)
    refuse_off = refuse_derived_for_grading_enabled()
    gradeable_flag_off = gradeable_subnet_counts(
        cache, refuse_derived=refuse_off
    )

    os.environ["REFUSE_DERIVED_FOR_GRADING"] = "on"
    refuse_on = refuse_derived_for_grading_enabled()
    gradeable_flag_on = gradeable_subnet_counts(cache, refuse_derived=refuse_on)

    if prev_refuse is None:
        os.environ.pop("REFUSE_DERIVED_FOR_GRADING", None)
    else:
        os.environ["REFUSE_DERIVED_FOR_GRADING"] = prev_refuse

    print("subnets_with_any_candles", any_candles)
    print(
        "gradeable_subnets_REFUSE_DERIVED_FOR_GRADING_off",
        gradeable_flag_off,
        "(env unset; refuse_derived=%s)" % refuse_off,
    )
    print(
        "gradeable_subnets_REFUSE_DERIVED_FOR_GRADING_on",
        gradeable_flag_on,
        "(REFUSE_DERIVED_FOR_GRADING=on; refuse_derived=%s)" % refuse_on,
    )
    print("gradeable_subnet_delta_flag_on", gradeable_flag_off - gradeable_flag_on)

    rows = list(_iter_resolved_rows(args.predictions))
    if not rows:
        print("predictions_resolved_rows", 0)
        print("note", f"no resolved rows at {args.predictions}")
        return
    counts = learning_export_guard_counts(rows)
    for key, value in counts.items():
        print(key, value)


if __name__ == "__main__":
    main()
