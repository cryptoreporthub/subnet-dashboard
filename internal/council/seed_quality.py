"""Image seed quality gates — reject placeholder S{n} seeds (#1479 PR-B)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from internal.council.score_snapshots import is_complete_snapshot
from internal.council.scorer_identity import finite_number

_PLACEHOLDER_NAME = re.compile(r"^S\d+$", re.IGNORECASE)
_FABRICATED_ALPHA_NAME = re.compile(r"^Alpha Subnet \d+$", re.IGNORECASE)
_REQUIRED_EXPERT_KEYS = ("quant", "hype", "dark_horse", "technical")


def _is_score(value: Any) -> bool:
    return finite_number(value)


def is_placeholder_seed_name(name: Any) -> bool:
    if not isinstance(name, str) or not name.strip():
        return True
    stripped = name.strip()
    if _PLACEHOLDER_NAME.match(stripped):
        return True
    return bool(_FABRICATED_ALPHA_NAME.match(stripped))


def seed_build_provenance(snap: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    prov = snap.get("build_provenance")
    return prov if isinstance(prov, dict) else None


def validate_shipped_seed(snap: Any) -> Tuple[bool, str]:
    """CI + test gate: real scorer build, not synthetic placeholder rows."""
    if not isinstance(snap, dict):
        return False, "not_a_dict"
    if not is_complete_snapshot(snap):
        return False, "incomplete_snapshot"
    prov = seed_build_provenance(snap)
    if not prov:
        return False, "missing_build_provenance"
    if prov.get("source") != "write_full_universe_snapshot":
        return False, "bad_provenance_source"
    try:
        succeeded = int(prov.get("day_succeeded_count") or 0)
        expected = int(prov.get("day_expected_count") or 0)
    except (TypeError, ValueError, OverflowError):  # int(float("inf")) raises OverflowError
        return False, "bad_provenance_counts"
    if expected < 1 or succeeded != expected:
        return False, "partial_build"
    day_rows: List[Dict[str, Any]] = [
        r for r in (snap.get("day") or []) if isinstance(r, dict)
    ]
    if len(day_rows) != succeeded:
        return False, "day_row_count_mismatch"
    for row in day_rows:
        if is_placeholder_seed_name(row.get("name")):
            return False, "placeholder_name"
        ec = row.get("expert_contributions")
        if not isinstance(ec, dict) or len(ec) < 2:
            return False, "missing_expert_contributions"
        # The producer scores all four council experts on every row (and the committed seed carries all
        # four plus extras), so require each with a finite number; extra keys are allowed.
        if not all(_is_score(ec.get(k)) for k in _REQUIRED_EXPERT_KEYS):
            return False, "expert_contributions_not_council_shaped"
    return True, "ok"
