"""Wallet classification into whale intelligence dimensions."""

from __future__ import annotations

from typing import Any, Dict, List


def score_dimensions(profile: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, float]:
    """Compute normalized scores for each tracking dimension."""
    holds = profile.get("hold_hours") or []
    median_hold = profile.get("median_hold_hours") or 72.0
    flip_count = profile.get("closed_trades", 0)
    thresholds = [float(t) for t in config.get("flip_thresholds_hours", [6, 24, 72])]

    flip_factor = min(1.0, flip_count / max(1, int(config.get("min_flip_count", 2))))
    time_factor = max(0.0, 1.0 - (median_hold / 72.0))
    rugger_risk = round(min(1.0, 0.4 * flip_factor + 0.6 * time_factor), 3)

    win_rate = float(profile.get("win_rate", 0))
    avg_return = float(profile.get("avg_return_pct") or 0)
    alpha_score = round(min(1.0, win_rate * 0.5 + min(1.0, max(0, avg_return) / 50.0) * 0.5), 3)

    impact = float(profile.get("avg_impact_score", 0))
    market_impact = round(min(1.0, impact), 3)

    early_moves = int(profile.get("early_moves", 0))
    early_score = round(min(1.0, early_moves / 5.0), 3)

    conviction_hold = float(config.get("conviction_min_hold_hours", 72))
    conviction_score = round(
        min(1.0, (median_hold / conviction_hold) * 0.5 + win_rate * 0.5), 3
    ) if median_hold >= conviction_hold * 0.5 else 0.0

    subnet_count = len(profile.get("subnets", []))
    rotator_min = int(config.get("rotator_min_subnets", 4))
    rotation_score = round(min(1.0, subnet_count / max(rotator_min, 1)), 3)

    return {
        "rugger_risk": rugger_risk,
        "alpha_score": alpha_score,
        "market_impact": market_impact,
        "early_mover": early_score,
        "conviction": conviction_score,
        "rotation": rotation_score,
    }


def classify_wallet(profile: Dict[str, Any], config: Dict[str, Any]) -> List[str]:
    """Assign wallet to one or more leaderboards."""
    scores = profile.get("scores") or score_dimensions(profile, config)
    classifications: List[str] = []

    closed = int(profile.get("closed_trades", 0))
    median_hold = profile.get("median_hold_hours")
    win_rate = float(profile.get("win_rate", 0))
    avg_return = profile.get("avg_return_pct")

    # Ruggers: short holds + poor outcomes (dumpers, not skilled scalpers)
    avg_return = profile.get("avg_return_pct")
    if (
        scores.get("rugger_risk", 0) >= float(config.get("rugger_risk_threshold", 0.65))
        and closed >= int(config.get("min_flip_count", 2))
        and median_hold is not None
        and median_hold <= max(config.get("flip_thresholds_hours", [72]))
        and win_rate < 0.5
        and (avg_return is None or avg_return <= 0)
    ):
        classifications.append("ruggers")

    # Alpha whales: proven winners (mutually exclusive with ruggers)
    if (
        "ruggers" not in classifications
        and closed >= int(config.get("alpha_min_closed_trades", 3))
        and win_rate >= float(config.get("alpha_min_win_rate", 0.55))
        and avg_return is not None
        and avg_return > 0
    ):
        classifications.append("alpha_whales")

    # Market movers: impact small caps
    if scores.get("market_impact", 0) >= float(config.get("market_mover_min_impact_score", 0.4)):
        classifications.append("market_movers")

    # Early movers: entries before big moves
    if int(profile.get("early_moves", 0)) >= 2:
        classifications.append("early_movers")

    # Conviction holders: long hold + positive track record
    if (
        median_hold is not None
        and median_hold >= float(config.get("conviction_min_hold_hours", 72))
        and win_rate >= 0.5
        and "ruggers" not in classifications
    ):
        classifications.append("conviction_holders")

    # Rotators: active across many subnets
    if len(profile.get("subnets", [])) >= int(config.get("rotator_min_subnets", 4)):
        classifications.append("rotators")

    return classifications
