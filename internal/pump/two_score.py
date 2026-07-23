"""Upgrade 5 — two-score split (predictive accum vs confirmatory).

Keeps existing ladder phase names (DORMANT→…→COOLING). Composite score
formula stays the calibration source of truth; accum/confirm are additive
layers for UI ownership, PUMPING gate, and Upgrade-6 features.
"""

from __future__ import annotations

from typing import Any, Dict

# Confirm score must clear this to enter PUMPING (else stay ACCUMULATING).
CONFIRM_PUMP_MIN = 0.35


def compute_accum_score(signals: Dict[str, Any]) -> float:
    """Layer A — predictive / flow-before-price (volume + buy pressure)."""
    vol = float(signals.get("volume_intensity") or 0)
    buy_ratio = float(signals.get("buy_ratio") or 0.5)
    chatter = float(signals.get("chatter_intensity") or 0)
    scenario_boost = 0.08 if signals.get("scenario_tag") else 0.0
    flow_term = max(buy_ratio - 0.5, 0.0) * 2.0
    score = (
        0.50 * vol
        + 0.30 * flow_term
        + 0.12 * chatter
        + scenario_boost
    )
    return round(min(max(score, 0.0), 1.0), 4)


def compute_confirm_score(signals: Dict[str, Any]) -> float:
    """Layer B — confirmatory price/momentum (+ light social velocity)."""
    mom = float(signals.get("momentum_1h") or 0)
    price = float(signals.get("price_change_24h") or 0)
    chatter = float(signals.get("chatter_intensity") or 0)
    mom_term = min(max(mom / 0.04, 0.0), 1.0)
    price_term = min(max(price / 0.08, 0.0), 1.0)
    score = 0.45 * mom_term + 0.40 * price_term + 0.15 * chatter
    return round(min(max(score, 0.0), 1.0), 4)


def score_layer_for_phase(phase: str) -> str:
    """UI ownership: predictive owns lead badges; confirm owns live/exit."""
    phase = str(phase or "").upper()
    if phase in {"STIRRING", "ACCUMULATING"}:
        return "predictive"
    if phase in {"PUMPING", "COOLING"}:
        return "confirm"
    return "none"


def apply_confirm_pump_gate(
    suggested: str,
    confirm_score: float,
    *,
    confirm_min: float = CONFIRM_PUMP_MIN,
) -> str:
    """PUMPING requires confirm layer; otherwise hold at ACCUMULATING."""
    if suggested == "PUMPING" and confirm_score < confirm_min:
        return "ACCUMULATING"
    return suggested
