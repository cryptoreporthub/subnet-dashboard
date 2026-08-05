"""Backfill missing council expert labels on prediction ledger rows."""

from __future__ import annotations

from typing import Any, Dict

from internal.council.expert_attribution import CANONICAL_EXPERTS, resolve_expert_attribution
from internal.learning.predictions_store import load_predictions, save_predictions


def backfill_expert_attribution(*, dry_run: bool = True) -> Dict[str, Any]:
    """Re-derive expert labels from signal_impact / pick metadata (expert fields only)."""
    data = load_predictions()
    would_update = 0
    updated = 0
    still_unknown = 0
    by_source: Dict[str, int] = {}

    for bucket in ("predictions", "resolved"):
        for row in data.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            expert, source = resolve_expert_attribution(row)
            if not expert:
                still_unknown += 1
                continue
            current = str(row.get("expert") or "").lower().strip()
            if current == expert and current in CANONICAL_EXPERTS:
                continue
            would_update += 1
            by_source[source] = by_source.get(source, 0) + 1
            if dry_run:
                continue
            row["expert"] = expert
            if source != "existing":
                row["expert_attribution_source"] = source
            updated += 1

    if not dry_run and updated > 0:
        save_predictions(data)

    return {
        "dry_run": bool(dry_run),
        "would_update": would_update,
        "updated": updated,
        "still_unknown": still_unknown,
        "by_source": by_source,
    }
