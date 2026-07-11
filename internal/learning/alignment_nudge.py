"""Apply Mindmap alignment scores to Council expert weights."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from internal.council.weights import SOUL_MAP_PATH, load_weights, save_weights
from internal.learning.trail_bus import emit_disposition_shift, emit_weight_change

logger = logging.getLogger(__name__)

_ALIGNMENT_DELTA = 0.01
_MIN = 0.1
_MAX = 2.0


def _expert_for_alignment_status(status: str) -> str:
    s = (status or "").lower()
    if s == "divergent":
        return "dark_horse"
    if s == "partially_aligned":
        return "technical"
    if s == "aligned":
        return "quant"
    return "hype"


def apply_alignment_nudge(feedback: Dict[str, Any]) -> Dict[str, Any]:
    """Nudge the expert weight that best matches selector↔brain alignment."""
    if not isinstance(feedback, dict):
        return {"applied": False, "reason": "invalid feedback"}

    alignment = float(feedback.get("alignment_score", 0.5) or 0.5)
    status = str(feedback.get("status", "partially_aligned"))
    expert = _expert_for_alignment_status(status)

    weights_before = load_weights(SOUL_MAP_PATH)
    before = float(weights_before.get(expert, 1.0))
    delta = _ALIGNMENT_DELTA if alignment >= 0.5 else -_ALIGNMENT_DELTA
    after = round(max(_MIN, min(_MAX, before + delta)), 4)
    weights_before[expert] = after
    save_weights(weights_before, SOUL_MAP_PATH)

    emit_weight_change(
        expert,
        before=before,
        after=after,
        reason=f"alignment_{status}",
        correct=alignment >= 0.75,
    )
    emit_disposition_shift(
        expert=expert,
        from_action="pre_alignment",
        to_action=status,
        evidence={"alignment_score": alignment, "expert_nudged": expert},
    )

    return {
        "applied": True,
        "expert": expert,
        "alignment_score": alignment,
        "status": status,
        "weight_before": before,
        "weight_after": after,
    }
