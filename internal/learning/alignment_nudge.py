"""Apply Mindmap alignment scores to Council expert weights."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from internal.council import weights as council_weights
from internal.learning.trail_bus import emit_disposition_shift, emit_weight_change

logger = logging.getLogger(__name__)

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

    weights_before = council_weights.load_weights(council_weights.SOUL_MAP_PATH)
    before = float(weights_before.get(expert, 1.0))
    after = None
    try:
        after = council_weights.nudge_expert(
            expert, alignment >= 0.5, council_weights.SOUL_MAP_PATH
        )
    except Exception:
        after = None
    if after is None:
        return {"applied": False, "reason": "nudge failed", "expert": expert}

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
