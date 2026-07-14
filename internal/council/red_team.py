"""
RedTeam audit layer for the Council daily pick.

Flags low liquidity, extreme volatility, unstable rank vs raw score, and
missing critical fields before a daily pick is promoted to the API.
"""

from typing import Any, Dict, List, Optional

from internal.subnets.tradable import is_tradable_subnet, subnet_netuid


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
    concerns: List[str] = []
    confidence_multiplier = 1.0

    # Root (netuid 0) is TAO staking infrastructure — never a tradable pick.
    if not is_tradable_subnet(candidate):
        n = subnet_netuid(candidate)
        label = "Root" if n == 0 else "missing/invalid netuid"
        concerns.append(f"Not a tradable subnet: {label}")
        confidence_multiplier = 0.0

    # Missing critical fields
    critical_fields = ("netuid", "name", "price", "volume")
    for field in critical_fields:
        value = candidate.get(field)
        if value is None or value == "":
            concerns.append(f"Missing critical field: {field}")
            confidence_multiplier *= 0.5

    # Liquidity check
    volume = float(candidate.get("volume", 0) or 0)
    if volume < 100_000:
        concerns.append(f"Low liquidity: volume ${volume:,.0f} < $100k")
        confidence_multiplier *= 0.80
    elif volume < 500_000:
        concerns.append(f"Thin volume: ${volume:,.0f} < $500k")
        confidence_multiplier *= 0.95

    # Extreme recent volatility
    chg24 = float(candidate.get("price_change_24h", 0) or 0)
    chg7 = float(candidate.get("price_change_7d", 0) or 0)
    if abs(chg24) > 20:
        concerns.append(f"Extreme 24h volatility: {chg24:+.1f}%")
        confidence_multiplier *= 0.85
    elif abs(chg24) > 12:
        concerns.append(f"Elevated 24h volatility: {chg24:+.1f}%")
        confidence_multiplier *= 0.95

    if abs(chg7) > 50:
        concerns.append(f"Extreme 7d volatility: {chg7:+.1f}%")
        confidence_multiplier *= 0.90

    # Risk flags
    risk_flags = candidate.get("risk_flags") or []
    if risk_flags:
        concerns.append(f"Risk flags present: {risk_flags}")
        confidence_multiplier *= 0.90

    if candidate.get("is_overvalued"):
        concerns.append("Subnet flagged as overvalued")
        confidence_multiplier *= 0.85

    if str(candidate.get("status", "active")).lower() in ("deprecated", "at-risk", "inactive"):
        concerns.append(f"Non-active status: {candidate.get('status')}")
        confidence_multiplier *= 0.70

    # Rank vs raw score stability: compare emission/market-cap rank to score rank
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
                concerns.append(
                    f"Unstable rank: score pick but emission rank #{emission_rank}"
                )
                confidence_multiplier *= 0.95
        except Exception:
            pass

    base_confidence = float(candidate.get("confidence", 0.5) or 0.5)
    adjusted = round(min(1.0, max(0.0, base_confidence * confidence_multiplier)), 4)
    missing_critical = any(c.startswith("Missing critical") for c in concerns)
    not_tradable = any(c.startswith("Not a tradable") for c in concerns)
    approved = not missing_critical and not not_tradable

    return {
        "approved": approved,
        "concerns": concerns,
        "adjusted_confidence": adjusted,
    }
