"""Canonical evidence population labels for prediction rows.

These labels are additive lineage metadata. They do not make an ungradeable
row trustworthy; they make it impossible to silently mix council, pump,
shadow, and archived measurements.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

# Coarse lineage buckets callers may mix in a report. Fine-grained labels
# stay on ``evidence_population``; this set is what ``evidence_source`` returns.
SOURCE_POPULATIONS: Tuple[str, ...] = (
    "council",
    "shadow",
    "pump",
    "archive",
    "unknown",
)


def evidence_population(row: Dict[str, Any]) -> str:
    if not isinstance(row, dict):
        return "unknown"
    if row.get("shadow") or row.get("counterfactual"):
        return "council_shadow"

    source = str(row.get("pick_source") or "").lower().strip()
    if source == "pump_combined_exp":
        return "pump_combined_experimental"
    if source == "pump_lead":
        claim = str(row.get("pump_claim") or row.get("pump_badge") or "").upper()
        if claim in {"JUST_STARTED", "JUST STARTED"}:
            return "pump_just_started"
        return "pump_early"
    if source == "council_shadow":
        return "council_shadow"
    if source in {"council", "council_pick", "daily_pick", "hour_pick"}:
        return "council_published"
    if row.get("archived") or row.get("archive_source"):
        return "archived"
    if row.get("signal_source") or row.get("expert"):
        return "legacy_unclassified"
    return "unknown"


def evidence_source(row: Dict[str, Any]) -> str:
    population = evidence_population(row)
    if population.startswith("pump_"):
        source = "pump"
    elif population == "council_shadow":
        source = "shadow"
    elif population == "council_published":
        source = "council"
    elif population == "archived":
        source = "archive"
    else:
        source = "unknown"
    return source if source in SOURCE_POPULATIONS else "unknown"


def stamp_evidence(row: Dict[str, Any]) -> bool:
    """Stamp additive source/population fields; return whether row changed."""
    if not isinstance(row, dict):
        return False
    population = evidence_population(row)
    source = evidence_source(row)
    changed = row.get("evidence_population") != population or row.get("evidence_source") != source
    row["evidence_population"] = population
    row["evidence_source"] = source
    return changed
