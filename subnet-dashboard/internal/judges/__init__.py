"""
Judge layer for the Subnet Dashboard Council / learning loop.

Provides three orthogonal judges:
  - OracleJudge: truthfulness / evidentiary quality
  - EchoJudge: resonance / consensus across signals
  - PulseJudge: momentum / energy behind a prediction

Each judge exposes ``evaluate(prediction, **kwargs) -> {score, confidence}``,
tracks a paper portfolio, and records scientific-method postmortems on wrong
picks.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from internal.judges import echo_judge, oracle_judge, pulse_judge
from internal.judges.judges import (
    ECHO,
    ORACLE,
    PULSE,
    EchoJudge,
    OracleJudge,
    PulseJudge,
    all_judges,
    get_judge,
)
from internal.judges.tracker import (
    on_prediction_created,
    on_prediction_resolved,
)


def run_judges(
    prediction: Dict[str, Any],
    signal_impact: Optional[Dict[str, Any]] = None,
    subnet: Optional[Dict[str, Any]] = None,
    expert_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Dict[str, float]]:
    """Run Oracle, Echo and Pulse against a prediction and return combined scores."""
    return {
        "oracle": oracle_judge.evaluate(prediction, signal_impact=signal_impact, subnet=subnet),
        "echo": echo_judge.evaluate(prediction, signal_impact=signal_impact, expert_weights=expert_weights),
        "pulse": pulse_judge.evaluate(prediction, signal_impact=signal_impact, subnet=subnet),
    }


def average_multiplier(judges: Dict[str, Dict[str, float]]) -> float:
    """Combine judge scores into a single learning-loop multiplier in [0.25, 1.5]."""
    if not judges:
        return 1.0
    total = 0.0
    weight = 0.0
    for name, result in judges.items():
        score = float(result.get("score", 0.5) or 0.5)
        conf = float(result.get("confidence", 0.5) or 0.5)
        total += score * conf
        weight += conf
    if weight <= 0:
        return 1.0
    avg = total / weight
    # Scale so a middling judge panel (0.5) maps to 1.0, strong (>0.8) amplifies,
    # weak (<0.4) dampens.
    multiplier = 0.5 + avg
    return max(0.25, min(1.5, multiplier))


__all__ = [
    "echo_judge",
    "oracle_judge",
    "pulse_judge",
    "run_judges",
    "average_multiplier",
    "OracleJudge",
    "EchoJudge",
    "PulseJudge",
    "ORACLE",
    "ECHO",
    "PULSE",
    "all_judges",
    "get_judge",
    "on_prediction_created",
    "on_prediction_resolved",
]
