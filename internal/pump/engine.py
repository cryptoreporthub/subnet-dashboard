"""Five-phase pump ladder classifier from live signals."""

from __future__ import annotations

from typing import Any, Dict

from internal.pump.constants import PHASE_ENTRY_THRESHOLDS, FORWARD_PHASES


def compute_composite_score(signals: Dict[str, Any]) -> float:
    """Blend volume, momentum, price action, message-intel, and scenario context."""
    vol = float(signals.get("volume_intensity") or 0)
    mom = float(signals.get("momentum_1h") or 0)
    price = float(signals.get("price_change_24h") or 0)
    buy_ratio = float(signals.get("buy_ratio") or 0.5)
    chatter = float(signals.get("chatter_intensity") or 0)
    scenario_boost = 0.08 if signals.get("scenario_tag") else 0.0

    mom_term = min(max(mom / 0.04, 0.0), 1.0)
    price_term = min(max(price / 0.08, 0.0), 1.0)
    flow_term = max(buy_ratio - 0.5, 0.0) * 2.0

    score = (
        0.30 * vol
        + 0.25 * mom_term
        + 0.20 * price_term
        + 0.10 * flow_term
        + 0.10 * chatter
        + scenario_boost
    )
    return round(min(max(score, 0.0), 1.0), 4)


def raw_phase_from_score(score: float, *, was_pumping: bool = False) -> str:
    """Map composite score to a target ladder phase (no hysteresis)."""
    if was_pumping and score < PHASE_ENTRY_THRESHOLDS["PUMPING"] and score >= PHASE_ENTRY_THRESHOLDS["COOLING"]:
        return "COOLING"
    target = "DORMANT"
    for phase in FORWARD_PHASES:
        if score >= PHASE_ENTRY_THRESHOLDS[phase]:
            target = phase
    if was_pumping and target == "ACCUMULATING" and score < 0.55:
        return "COOLING"
    return target


def classify_signals(signals: Dict[str, Any], *, current_phase: str = "DORMANT") -> Dict[str, Any]:
    """Return classification payload for one subnet."""
    score = compute_composite_score(signals)
    was_pumping = current_phase in ("PUMPING", "COOLING")
    suggested = raw_phase_from_score(score, was_pumping=was_pumping)
    return {
        "netuid": signals.get("netuid"),
        "name": signals.get("name"),
        "composite_score": score,
        "suggested_phase": suggested,
        "signals": signals,
    }


def build_ladder_snapshot(path: str | None = None) -> Dict[str, Any]:
    """Agent B adapter import — delegates to persisted ladder state."""
    from internal.pump.constants import STATE_PATH

    from internal.pump.state import build_ladder_snapshot as _build

    return _build(path)


def get_top_movers(limit: int = 20) -> Dict[str, Any]:
    """Agent B adapter import — recent transitions from ladder state."""
    from internal.pump.state import get_top_movers as _top

    return _top(limit=limit)
