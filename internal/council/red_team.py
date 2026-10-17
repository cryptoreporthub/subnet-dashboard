"""
RedTeam audit layer for the Council daily pick.

Flags low liquidity, extreme volatility, unstable rank vs raw score, and
missing critical fields before a daily pick is promoted to the API.

Multipliers are calibrated against graded predictions (2026-07-26): volume and
emission-rank flags did not predict worse hit rates in the n≈60 sample, so they
are notes with tiny haircuts. Stacked cuts are capped (RED_TEAM_MAX_HAIRCUT).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from internal.subnets.tradable import is_tradable_subnet, subnet_netuid, subnet_volume


def _max_haircut_fraction() -> float:
    """Max confidence reduction from stacked audit multipliers (default 12%)."""
    raw = os.environ.get("RED_TEAM_MAX_HAIRCUT", "0.12").strip()
    try:
        val = float(raw)
    except ValueError:
        val = 0.12
    return max(0.05, min(0.35, val))


def _apply_multiplier(multiplier: float, factor: float) -> float:
    floor = 1.0 - _max_haircut_fraction()
    return max(floor, multiplier * factor)


# Concern codes. Blocking concerns make ``approved`` False; the rest are advisory haircuts.
NOT_TRADABLE = "not_tradable"
MISSING_CRITICAL_FIELD = "missing_critical_field"
BLOCKING_CODES = frozenset({NOT_TRADABLE, MISSING_CRITICAL_FIELD})


@dataclass(frozen=True)
class Concern:
    code: str
    message: str

    @property
    def blocking(self) -> bool:
        return self.code in BLOCKING_CODES


def has_concern(audit: Optional[Dict[str, Any]], code: str) -> bool:
    """True when ``audit`` carries a concern with this code.

    Audits stored before codes existed (pre 2026-10-17) only have message strings; those are
    matched by their original message prefix so historical rows still classify.
    """
    if not isinstance(audit, dict):
        return False
    codes = audit.get("concern_codes")
    if isinstance(codes, list):
        return code in codes
    legacy_prefix = {NOT_TRADABLE: "Not a tradable", MISSING_CRITICAL_FIELD: "Missing critical"}[code]
    return any(str(c).startswith(legacy_prefix) for c in (audit.get("concerns") or []))


def audit_daily_pick(
    candidate: Dict[str, Any],
    all_subnets: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Audit a candidate daily pick and return an approval verdict.

    Args:
        candidate: The selected subnet dict (or enriched pick payload).
        all_subnets: Full universe for rank-stability cross-checks.

    Returns:
        dict with approved (bool), concerns (list), adjusted_confidence (float).
    """
    candidate = candidate or {}
    all_subnets = all_subnets or []
    found: List[Concern] = []
    confidence_multiplier = 1.0
    blocked = False

    def cut(factor: float) -> None:
        """Apply an advisory haircut; a blocked candidate stays at zero confidence."""
        nonlocal confidence_multiplier
        if not blocked:
            confidence_multiplier = _apply_multiplier(confidence_multiplier, factor)

    # Root (netuid 0) is TAO staking infrastructure — never a tradable pick.
    if not is_tradable_subnet(candidate):
        n = subnet_netuid(candidate)
        label = "Root" if n == 0 else "missing/invalid netuid"
        found.append(Concern(NOT_TRADABLE, f"Not a tradable subnet: {label}"))
        blocked = True
        confidence_multiplier = 0.0

    # Missing critical fields
    critical_fields = ("netuid", "name", "price", "volume")
    for field in critical_fields:
        value = candidate.get(field)
        if field == "volume" and (value is None or value == ""):
            # Chain merges expose buy/sell volume instead of unified volume.
            if subnet_volume(candidate) > 0:
                continue
        if value is None or value == "":
            found.append(Concern(MISSING_CRITICAL_FIELD, f"Missing critical field: {field}"))
            blocked = True
            confidence_multiplier = 0.0

    # Liquidity — alpha turnover is typically $0.5k–$50k/day.
    # Graded sample: volume<$500 hit ≈ base rate; do not crush thin names.
    volume = subnet_volume(candidate)
    if volume < 100:
        found.append(Concern("advisory", f"Very thin volume: ${volume:,.0f} < $100"))
        cut(0.97)
    elif volume < 500:
        found.append(Concern("advisory", f"Low liquidity: volume ${volume:,.0f} < $500"))
        cut(0.98)
    elif volume < 5_000:
        found.append(Concern("advisory", f"Thin volume: ${volume:,.0f} < $5k"))
        cut(0.99)

    # Volatility — momentum can be the edge; haircuts are mild notes.
    chg24 = float(candidate.get("price_change_24h", 0) or 0)
    chg7 = float(candidate.get("price_change_7d", 0) or 0)
    if abs(chg24) > 20:
        found.append(Concern("advisory", f"Extreme 24h volatility: {chg24:+.1f}%"))
        cut(0.92)
    elif abs(chg24) > 12:
        found.append(Concern("advisory", f"Elevated 24h volatility: {chg24:+.1f}%"))
        cut(0.98)

    if abs(chg7) > 50:
        found.append(Concern("advisory", f"Extreme 7d volatility: {chg7:+.1f}%"))
        cut(0.95)

    # Real risk — keep meaningful, but never stack to a second HOLD via audit alone.
    risk_flags = candidate.get("risk_flags") or []
    if risk_flags:
        found.append(Concern("advisory", f"Risk flags present: {risk_flags}"))
        cut(0.95)

    if candidate.get("is_overvalued"):
        found.append(Concern("advisory", "Subnet flagged as overvalued"))
        cut(0.92)

    if str(candidate.get("status", "active")).lower() in ("deprecated", "at-risk", "inactive"):
        found.append(Concern("advisory", f"Non-active status: {candidate.get('status')}"))
        cut(0.90)

    # Emission-rank mismatch: note only — did not predict misses in graded sample.
    if all_subnets and len(all_subnets) > 1:
        netuid = candidate.get("netuid")
        try:
            sorted_by_emission = sorted(
                [s for s in all_subnets if s.get("emission") is not None],
                key=lambda s: float(s.get("emission", 0) or 0),
                reverse=True,
            )
            emission_rank = next(
                (i + 1 for i, s in enumerate(sorted_by_emission) if s.get("netuid") == netuid),
                None,
            )
            if emission_rank and emission_rank > max(3, len(sorted_by_emission) // 3):
                found.append(Concern(
                    "advisory", f"Unstable rank: score pick but emission rank #{emission_rank}"
                ))
                cut(0.98)
        except Exception:
            pass

    base_confidence = float(candidate.get("confidence", 0.5) or 0.5)
    adjusted = round(min(1.0, max(0.0, base_confidence * confidence_multiplier)), 4)
    approved = not any(c.blocking for c in found)

    return {
        "approved": approved,
        "blocked": blocked,
        "concerns": [c.message for c in found],
        "concern_codes": [c.code for c in found],
        "adjusted_confidence": adjusted,
        "confidence_multiplier": round(confidence_multiplier, 4),
        "max_haircut": _max_haircut_fraction(),
    }
