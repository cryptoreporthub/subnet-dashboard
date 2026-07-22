"""Score-time pump desk prior — blends into council total, never soul_map weights."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

_EARLY_PHASES = frozenset({"STIRRING", "ACCUMULATING"})
_CONFIRMED_PHASES = frozenset({"PUMPING"})


def overlay_alpha() -> float:
    raw = os.environ.get("PUMP_SCORE_OVERLAY_ALPHA", "0.10").strip()
    try:
        alpha = float(raw)
    except (TypeError, ValueError):
        alpha = 0.10
    return max(0.0, min(0.25, alpha))


def pump_ladder_entry(netuid: int) -> Optional[Dict[str, Any]]:
    try:
        from internal.pump.state import load_state

        st = load_state()
        subnets = st.get("subnets") if isinstance(st, dict) else {}
        if not isinstance(subnets, dict):
            return None
        entry = subnets.get(str(netuid)) or subnets.get(netuid)
        return dict(entry) if isinstance(entry, dict) else None
    except Exception:
        return None


def pump_prior_0_1(entry: Dict[str, Any]) -> Optional[float]:
    """Map ladder phase + composite score → 0..1 bullish prior."""
    phase = str(entry.get("phase") or "DORMANT").upper()
    try:
        score = float(entry.get("composite_score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))
    if phase in _EARLY_PHASES:
        return round(0.42 + score * 0.35, 4)
    if phase in _CONFIRMED_PHASES:
        return round(0.38 + score * 0.28, 4)
    if phase == "COOLING":
        return round(0.28 + score * 0.12, 4)
    return None


def apply_pump_score_overlay(
    total_score: float,
    subnet_data: Dict[str, Any],
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """Blend council total (0–100) with pump prior. No persistence."""
    alpha = overlay_alpha()
    if alpha <= 0:
        return total_score, None
    netuid = subnet_data.get("netuid") or subnet_data.get("id")
    if netuid is None:
        return total_score, None
    try:
        nu = int(netuid)
    except (TypeError, ValueError):
        return total_score, None
    entry = pump_ladder_entry(nu)
    if not entry:
        return total_score, None
    prior = pump_prior_0_1(entry)
    if prior is None:
        return total_score, None
    prior_pct = prior * 100.0
    blended = round((1.0 - alpha) * float(total_score) + alpha * prior_pct, 2)
    blended = min(100.0, max(0.0, blended))
    return blended, {
        "alpha": alpha,
        "prior": prior,
        "phase": str(entry.get("phase") or "").upper(),
        "composite_score": entry.get("composite_score"),
        "before": round(float(total_score), 2),
        "after": blended,
    }
