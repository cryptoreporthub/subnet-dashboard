"""Relative market impact — same TAO flow hits small caps harder than large caps.

Historical product intent (Ditto): focus alpha on small/mid caps, not by
hard-excluding the top ~30 market caps, but by scoring **price impact**:
100 TAO into Chutes barely moves the float; 50 TAO into a thin name does.

``impact_strength`` (soul_map / env) is the adjustable dial:
  0 = no size correction, 1 = default, 2 = aggressive small-cap tilt.
SimiVision nudges it when resolved picks show over/under-correction.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from internal.subnets.tradable import subnet_volume

# Mid-cap reference size (TMC market_cap units). Sensitivity ≈ BASELINE / size.
_BASELINE_MCAP = 20_000.0
# Canonical order size for UI / prediction framing.
REFERENCE_TAO = 50.0


def _strength(override: Optional[float] = None) -> float:
    if override is not None:
        try:
            return max(0.0, min(2.0, float(override)))
        except (TypeError, ValueError):
            pass
    try:
        from internal.council.weights import load_impact_strength

        return float(load_impact_strength())
    except Exception:
        return 1.0


def subnet_market_cap(sn: Dict[str, Any]) -> float:
    """Market size proxy: TMC market_cap, else total_stake (TAO)."""
    if not isinstance(sn, dict):
        return 0.0
    try:
        mcap = float(sn.get("market_cap") or 0)
    except (TypeError, ValueError):
        mcap = 0.0
    if mcap > 0:
        return mcap
    for key in ("total_stake", "stake", "total_stake_tao"):
        try:
            stake = float(sn.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if stake > 0:
            return stake
    return 0.0


def relative_flow(sn: Dict[str, Any]) -> float:
    """24h turnover as a fraction of market size (vol / mcap)."""
    size = subnet_market_cap(sn)
    if size <= 0:
        return 0.0
    return subnet_volume(sn) / size


def impact_sensitivity(sn: Dict[str, Any]) -> float:
    """How movable the name is vs a mid-cap baseline (higher = thinner).

    Large caps (~Chutes) land near the floor (~0.05); small/mid cluster around 1+;
    micros can amplify up to 8× (clamped). Independent of strength dial.
    """
    size = subnet_market_cap(sn)
    if size <= 0:
        return 1.0
    return max(0.05, min(8.0, _BASELINE_MCAP / size))


def impact_scale_factor(sn: Dict[str, Any], strength: Optional[float] = None) -> float:
    """Map sensitivity through the strength dial.

    ``sens ** (0.5 * strength)`` — strength 0 → 1.0 (flat), 1 → √sens, 2 → sens.
    """
    sens = impact_sensitivity(sn)
    s = _strength(strength)
    if s <= 0:
        return 1.0
    return max(0.05, min(8.0, sens ** (0.5 * s)))


def tao_order_impact_pct(sn: Dict[str, Any], tao_amount: float = REFERENCE_TAO) -> float:
    """Rough % of float a ``tao_amount`` order represents (size proxy)."""
    size = subnet_market_cap(sn)
    if size <= 0:
        depth = max(subnet_volume(sn), 1.0)
        return round(100.0 * float(tao_amount) / depth, 4)
    return round(100.0 * float(tao_amount) / size, 4)


def impact_tier(sn: Dict[str, Any]) -> str:
    """large / mid / small from sensitivity (keeps large caps visible, not filtered)."""
    sens = impact_sensitivity(sn)
    if sens < 0.25:
        return "large"
    if sens < 1.0:
        return "mid"
    return "small"


def scale_move_by_impact(
    raw_pct: float,
    sn: Dict[str, Any],
    strength: Optional[float] = None,
) -> float:
    """Scale a raw predicted % move by the strength-tuned impact factor."""
    factor = impact_scale_factor(sn, strength)
    return round(float(raw_pct) * factor, 4)


def impact_profile(
    sn: Dict[str, Any],
    tao_amount: float = REFERENCE_TAO,
    strength: Optional[float] = None,
) -> Dict[str, Any]:
    """Compact impact block for pick payloads and reasons."""
    size = subnet_market_cap(sn)
    sens = impact_sensitivity(sn)
    s = _strength(strength)
    factor = impact_scale_factor(sn, s)
    flow = relative_flow(sn)
    ref_pct = tao_order_impact_pct(sn, tao_amount)
    tier = impact_tier(sn)
    summary = (
        f"{tier}-cap: {tao_amount:.0f} TAO ≈ {ref_pct:.2f}% of float"
        if size > 0
        else f"{tier}-cap: size unknown — neutral impact"
    )
    if abs(s - 1.0) >= 0.01:
        summary = f"{summary} · strength {s:.2f}"
    return {
        "tier": tier,
        "market_cap": round(size, 2) if size else 0.0,
        "relative_flow": round(flow, 4),
        "sensitivity": round(sens, 3),
        "strength": round(s, 4),
        "scale_factor": round(factor, 4),
        "ref_tao": float(tao_amount),
        "ref_impact_pct": ref_pct,
        "summary": summary,
    }


def impact_reason(
    sn: Dict[str, Any],
    tao_amount: float = REFERENCE_TAO,
    strength: Optional[float] = None,
) -> Optional[str]:
    """One display line for council/SimiVision reasons."""
    profile = impact_profile(sn, tao_amount, strength)
    if not profile["market_cap"]:
        return None
    tier = profile["tier"]
    ref = profile["ref_impact_pct"]
    flow = profile["relative_flow"]
    s = profile["strength"]
    suffix = f" · dial {s:.2f}" if abs(s - 1.0) >= 0.01 else ""
    if tier == "large":
        return f"Large-cap dampened: {tao_amount:.0f} TAO ≈ {ref:.3f}% of float{suffix}"
    if flow >= 0.1:
        return f"High relative flow ({flow:.0%} of float) — {tao_amount:.0f} TAO ≈ {ref:.2f}%{suffix}"
    return f"{tier.capitalize()}-cap impact: {tao_amount:.0f} TAO ≈ {ref:.2f}% of float{suffix}"
