"""Central publish gate for council daily picks (env-tunable).

Human-locked 2026-07-26: default was 40%. Acc-2 (2026-07-30) raised to 50% after
archive review — sub-45% bucket net-negative. Rollback: DAILY_PICK_PUBLISH_GATE=0.40.
"""

from __future__ import annotations

import os
from typing import Any, Dict

_DEFAULT_GATE = 0.50


def publish_gate_fraction() -> float:
    """Minimum audited ``final_confidence`` required to publish a LONG call."""
    raw = os.environ.get("DAILY_PICK_PUBLISH_GATE", str(_DEFAULT_GATE)).strip()
    try:
        gate = float(raw)
    except ValueError:
        gate = _DEFAULT_GATE
    return max(0.30, min(0.60, gate))


def publish_gate_percent() -> int:
    return int(round(publish_gate_fraction() * 100))


def publish_gate_label() -> str:
    return f"{publish_gate_percent()}% audit gate"


def directional_publish_guard(pick: Dict[str, Any]) -> Dict[str, Any]:
    """Block a published LONG when its own signal direction is bearish."""
    impact = pick.get("signal_impact") if isinstance(pick, dict) else {}
    impact = impact if isinstance(impact, dict) else {}
    direction = str(impact.get("net_direction") or "").lower()
    try:
        predicted_pct = float(impact.get("net_predicted_pct"))
    except (TypeError, ValueError):
        predicted_pct = None
    if direction == "bearish" or (predicted_pct is not None and predicted_pct < 0):
        return {
            "approved": False,
            "reason": "Directional conflict: council signal is bearish; no LONG published.",
            "direction": direction or None,
            "predicted_pct": predicted_pct,
        }
    return {
        "approved": True,
        "reason": None,
        "direction": direction or None,
        "predicted_pct": predicted_pct,
    }
