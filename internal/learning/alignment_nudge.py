"""Apply Mindmap alignment scores to Council expert weights."""

from __future__ import annotations

import logging
from typing import Any, Dict

from internal.council import weights as council_weights
from internal.learning.trail_bus import emit_disposition_shift

logger = logging.getLogger(__name__)

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
    """Record selector↔brain alignment without changing outcome weights.

    Alignment is a diagnostic about agreement between two selectors, not a
    verified market outcome. Mixing it into outcome weights made Quant appear
    learned with zero attributed grades.
    """
    if not isinstance(feedback, dict):
        return {"applied": False, "reason": "invalid feedback"}

    alignment = float(feedback.get("alignment_score", 0.5) or 0.5)
    status = str(feedback.get("status", "partially_aligned"))
    expert = _expert_for_alignment_status(status)

    weights_before = council_weights.load_weights(council_weights.SOUL_MAP_PATH)
    before = float(weights_before.get(expert, 1.0))
    emit_disposition_shift(
        expert=expert,
        from_action="pre_alignment",
        to_action=status,
        evidence={
            "alignment_score": alignment,
            "expert_observed": expert,
            "outcome_weight_changed": False,
        },
    )

    return {
        "applied": False,
        "diagnostic_recorded": True,
        "reason": "alignment_diagnostic_only",
        "expert": expert,
        "alignment_score": alignment,
        "status": status,
        "weight_before": before,
        "weight_after": before,
    }
