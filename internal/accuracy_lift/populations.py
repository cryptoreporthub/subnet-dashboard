"""Row population buckets for accuracy_lift (mirror trust vs full ledger)."""

from __future__ import annotations

from typing import Any, Dict

from internal.council.grading import is_pump_combined_exp, is_pump_desk_claim, is_pump_lead

_SKIP_OUTCOMES = frozenset({"duplicate", "expired", "ungradeable"})
_COUNCIL_SOURCES = frozenset({"", "council"})


def _pick_source_raw(row: Dict[str, Any]) -> str:
    return str(row.get("pick_source") or "").lower().strip()


def is_shadow_row(row: Dict[str, Any]) -> bool:
    if bool(row.get("shadow") or row.get("counterfactual")):
        return True
    return _pick_source_raw(row) == "council_shadow"


def is_gradable_row(row: Dict[str, Any]) -> bool:
    """Resolver-exact: stored correct only (matches _compute_stats gradable)."""
    if not isinstance(row, dict):
        return False
    if str(row.get("outcome") or "").lower() in _SKIP_OUTCOMES:
        return False
    return row.get("correct") is not None


def is_council_trust_row(row: Dict[str, Any]) -> bool:
    """Same population as resolver._compute_stats gradable rows."""
    if not is_gradable_row(row):
        return False
    if is_pump_desk_claim(row):
        return False
    if is_shadow_row(row):
        return False
    return True


def population_of(row: Dict[str, Any]) -> str:
    """LOCK vocabulary: pump | shadow | council | other."""
    if is_pump_lead(row):
        return "pump_lead"
    if is_pump_combined_exp(row):
        return "pump_combined_exp"
    if is_shadow_row(row):
        return "shadow"
    source = _pick_source_raw(row)
    if source in _COUNCIL_SOURCES:
        return "council"
    return source if source else "council"


def is_published_council_row(row: Dict[str, Any]) -> bool:
    """Mirror resolver._compute_stats gradable filter (published council picks)."""
    if population_of(row) != "council":
        return False
    if str(row.get("outcome") or "").lower() in _SKIP_OUTCOMES:
        return False
    return row.get("correct") is not None or row.get("actual_pct") is not None


def pick_source_bucket(row: Dict[str, Any]) -> str:
    bucket = population_of(row)
    if bucket == "shadow":
        return "council_shadow"
    return bucket
