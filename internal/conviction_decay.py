"""
Conviction Decay system for the Mindmap.

Every signal/hypothesis/verdict node gets a created_at timestamp and a
half_life_hours value. Nodes are rendered with opacity proportional to
remaining alpha: alpha = e^(-λt) where λ = ln(2)/half_life.

Decay Resistance: a hypothesis that was CORRECT (outcome score >= 0.7)
gets a decay_resistance_multiplier of 3.0 — stays bright 3x longer.
A hypothesis that was WRONG (outcome score < 0.3) decays on normal schedule.

Auto-pruning: nodes below DECAY_PRUNE_THRESHOLD (default 0.05) are pruned
from active state but remain in history (queryable, not rendered).
"""

import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DECAY_PRUNE_THRESHOLD = float(os.environ.get("DECAY_PRUNE_THRESHOLD", "0.05"))

# Half-life in hours by signal type.
DEFAULT_HALF_LIFE_HOURS: Dict[str, float] = {
    "whale_alert": 0.33,
    "emission_change": 1.4,
    "discord_spike": 2.3,
    "governance": 14.0,
    "price_signal": 4.0,
    "social_surge": 1.8,
    "technical_indicator": 6.0,
    "hypothesis": 24.0,
    "verdict": 48.0,
    "default": 8.0,
}

DECAY_RESISTANCE_MULTIPLIER = 3.0
CORRECT_THRESHOLD = 0.7
WRONG_THRESHOLD = 0.3


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _hours_since(created_at: str) -> float:
    """Return hours elapsed since created_at (ISO timestamp)."""
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        delta = _now_utc() - created
        return delta.total_seconds() / 3600.0
    except Exception:
        return 0.0


def compute_alpha(
    created_at: str,
    half_life_hours: Optional[float] = None,
    signal_type: Optional[str] = None,
    outcome_score: Optional[float] = None,
) -> float:
    """
    Compute remaining alpha (opacity) for a node.

    alpha = e^(-λt) where λ = ln(2) / half_life

    If outcome_score is provided:
      - score >= CORRECT_THRESHOLD → half_life *= DECAY_RESISTANCE_MULTIPLIER
      - score < WRONG_THRESHOLD → normal decay
    """
    hl = half_life_hours or DEFAULT_HALF_LIFE_HOURS.get(
        signal_type or "default", DEFAULT_HALF_LIFE_HOURS["default"]
    )

    if outcome_score is not None and outcome_score >= CORRECT_THRESHOLD:
        hl *= DECAY_RESISTANCE_MULTIPLIER

    t = _hours_since(created_at)
    if t <= 0:
        return 1.0

    lam = math.log(2) / hl
    alpha = math.exp(-lam * t)
    return max(0.0, alpha)


def is_pruned(alpha: float, threshold: float = DECAY_PRUNE_THRESHOLD) -> bool:
    """Return True if the node should be pruned from active state."""
    return alpha < threshold


def apply_decay_to_nodes(
    nodes: List[Dict[str, Any]],
    prune_threshold: float = DECAY_PRUNE_THRESHOLD,
) -> Dict[str, Any]:
    """
    Apply conviction decay to a list of nodes.

    Returns:
        {
            "active": [...],   # nodes with alpha >= threshold
            "pruned": [...],   # nodes with alpha < threshold (history only)
            "pruned_count": int,
            "active_count": int,
        }
    """
    active = []
    pruned = []

    for node in nodes:
        alpha = compute_alpha(
            created_at=node.get("created_at", _now_utc().isoformat()),
            half_life_hours=node.get("half_life_hours"),
            signal_type=node.get("signal_type"),
            outcome_score=node.get("outcome_score"),
        )
        node["alpha"] = round(alpha, 6)
        node["decayed_at"] = _now_utc().isoformat()

        if is_pruned(alpha, prune_threshold):
            node["pruned"] = True
            pruned.append(node)
        else:
            node["pruned"] = False
            active.append(node)

    return {
        "active": active,
        "pruned": pruned,
        "pruned_count": len(pruned),
        "active_count": len(active),
    }


def get_half_life(signal_type: str) -> float:
    """Return the half-life in hours for a given signal type."""
    return DEFAULT_HALF_LIFE_HOURS.get(signal_type, DEFAULT_HALF_LIFE_HOURS["default"])


def node_metadata(
    signal_type: str,
    outcome_score: Optional[float] = None,
    half_life_hours: Optional[float] = None,
) -> Dict[str, Any]:
    """Build standard decay metadata for a new node."""
    hl = half_life_hours or get_half_life(signal_type)
    return {
        "created_at": _now_utc().isoformat(),
        "half_life_hours": hl,
        "signal_type": signal_type,
        "outcome_score": outcome_score,
        "alpha": 1.0,
        "pruned": False,
    }