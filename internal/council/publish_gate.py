"""Central publish gate for council daily picks (env-tunable).

Human-locked 2026-07-26: default 40%. Wait on sub-40 until prod data at 40%
is reviewed (red-team was often the binding constraint, not the gate).
"""

from __future__ import annotations

import os

_DEFAULT_GATE = 0.40


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
