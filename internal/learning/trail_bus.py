"""Trail bus helpers — call existing emit_trail_event with canonical Phase B types.

DO NOT duplicate trail_events.py; import emit_trail_event only.
Canonical types: prediction_resolved, disposition_shift, weight_change,
accuracy_update, signal_triggered, scenario_tagged, conviction_update.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from internal.learning.trail_events import emit_trail_event

CANONICAL_EVENT_TYPES = frozenset(
    {
        "prediction_resolved",
        "disposition_shift",
        "weight_change",
        "accuracy_update",
        "signal_triggered",
        "scenario_tagged",
        "conviction_update",
    }
)


def normalize_event_type(raw: Optional[str]) -> str:
    if not raw:
        return "signal_triggered"
    key = str(raw).lower().strip()
    aliases = {
        "prediction_resolved": "prediction_resolved",
        "rotation_tokens_update": "conviction_update",
        "weight_nudge_up": "weight_change",
        "weight_nudge_down": "weight_change",
        "pick_recorded": "conviction_update",
        "judge_postmortem": "disposition_shift",
        "judge_pnl": "accuracy_update",
        "selector_rotation": "disposition_shift",
        "alignment_nudge": "weight_change",
    }
    if key in CANONICAL_EVENT_TYPES:
        return key
    return aliases.get(key, key if key in CANONICAL_EVENT_TYPES else "signal_triggered")


def emit_weight_change(
    expert: str,
    *,
    before: float,
    after: float,
    reason: str,
    correct: Optional[bool] = None,
) -> None:
    emit_trail_event(
        "weight_change",
        judge=expert,
        evidence={"before": before, "after": after, "delta": round(after - before, 4), "reason": reason},
        decision="nudge_up" if after > before else "nudge_down",
        signal="learning_loop",
        extra={"correct": correct},
    )


def emit_accuracy_update(
    *,
    accuracy: float,
    correct: int,
    wrong: int,
    pending: int,
    resolved_now: int = 0,
) -> None:
    emit_trail_event(
        "accuracy_update",
        evidence={
            "accuracy": accuracy,
            "correct": correct,
            "wrong": wrong,
            "pending": pending,
            "resolved_now": resolved_now,
        },
        decision="learning_metrics_refresh",
        signal="resolver",
    )


def emit_disposition_shift(
    *,
    subnet: Optional[str] = None,
    netuid: Optional[Any] = None,
    from_action: Optional[str] = None,
    to_action: Optional[str] = None,
    expert: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> None:
    emit_trail_event(
        "disposition_shift",
        subnet=subnet,
        netuid=netuid,
        judge=expert,
        evidence={
            **(evidence or {}),
            "from_action": from_action,
            "to_action": to_action,
        },
        decision=to_action,
        signal="council_selector",
    )


def emit_scenario_tagged(scenario: Dict[str, Any]) -> None:
    emit_trail_event(
        "scenario_tagged",
        subnet=scenario.get("name"),
        evidence={
            "scenario_id": scenario.get("id"),
            "features": scenario.get("features"),
            "regime": scenario.get("regime"),
            "outcome": scenario.get("outcome"),
        },
        decision=scenario.get("outcome") or "pending",
        signal="scenario_memory",
    )


def emit_conviction_update(
    *,
    subnet: Optional[str] = None,
    netuid: Optional[Any] = None,
    conviction: Optional[float] = None,
    horizon_type: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> None:
    emit_trail_event(
        "conviction_update",
        subnet=subnet,
        netuid=netuid,
        evidence={**(evidence or {}), "conviction": conviction, "horizon_type": horizon_type},
        decision="pick_conviction",
        signal="council_picks",
    )


def emit_signal_triggered(
    *,
    subnet: Optional[str] = None,
    netuid: Optional[Any] = None,
    signal_name: str,
    direction: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> None:
    emit_trail_event(
        "signal_triggered",
        subnet=subnet,
        netuid=netuid,
        signal=signal_name,
        evidence=evidence or {},
        decision=direction,
    )


def emit_judge_postmortem(
    judge_name: str,
    prediction: Dict[str, Any],
    postmortem: Optional[Dict[str, Any]],
) -> None:
    emit_trail_event(
        "disposition_shift",
        subnet=prediction.get("name"),
        netuid=prediction.get("netuid"),
        judge=judge_name,
        evidence={"postmortem": postmortem, "prediction_id": prediction.get("id")},
        decision="post_mortem_recorded",
        signal="judge_council",
        prediction=prediction.get("statement"),
    )


def emit_judge_pnl(
    judge_name: str,
    prediction: Dict[str, Any],
    closed: Optional[Dict[str, Any]],
) -> None:
    if not isinstance(closed, dict):
        return
    emit_trail_event(
        "accuracy_update",
        subnet=prediction.get("name"),
        netuid=prediction.get("netuid"),
        judge=judge_name,
        evidence={
            "pnl_pct": closed.get("pnl_pct"),
            "won": closed.get("won"),
            "prediction_id": prediction.get("id"),
        },
        decision="position_closed",
        signal="judge_portfolio",
    )
