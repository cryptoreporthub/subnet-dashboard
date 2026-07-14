"""Mindmap trail events for the learning loop (no data dead-ends)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _now_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def emit_trail_event(
    event_type: str,
    *,
    subnet: Optional[str] = None,
    netuid: Optional[Any] = None,
    evidence: Optional[Dict[str, Any]] = None,
    signal: Optional[str] = None,
    decision: Optional[str] = None,
    prediction: Optional[str] = None,
    judge: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Append a learning-trail row via MindmapBridge (merged soul_map save)."""
    entry: Dict[str, Any] = {
        "time": _now_z(),
        "event_type": event_type,
        "subnet": subnet,
        "netuid": netuid,
        "evidence": evidence or {},
        "signal": signal,
        "decision": decision,
        "prediction": prediction,
        "judge": judge,
    }
    if extra:
        entry.update(extra)
    try:
        from internal.council.mindmap_bridge import MindmapBridge
        from internal.council.weights import SOUL_MAP_PATH

        MindmapBridge(persistence_path=SOUL_MAP_PATH).append_learning_trail(entry)
    except Exception as exc:
        logger.warning("Trail event %s failed: %s", event_type, exc)


def emit_prediction_resolved(prediction: Dict[str, Any], expert: Optional[str]) -> None:
    """Trail event when a prediction resolves and nudges expert weights."""
    correct = prediction.get("correct")
    outcome = prediction.get("outcome")
    impact = prediction.get("market_impact") if isinstance(prediction.get("market_impact"), dict) else {}
    emit_trail_event(
        "prediction_resolved",
        subnet=prediction.get("name"),
        netuid=prediction.get("netuid"),
        evidence={
            "prediction_id": prediction.get("id"),
            "outcome": outcome,
            "correct": correct,
            "actual_pct": prediction.get("actual_pct"),
            "predicted_pct": prediction.get("predicted_pct"),
            "horizon_type": prediction.get("horizon_type"),
            "impact_tier": prediction.get("impact_tier") or impact.get("tier"),
            "impact_strength_at_creation": prediction.get("impact_strength_at_creation")
            or prediction.get("impact_strength"),
            "impact_strength_after": prediction.get("impact_strength_after"),
        },
        signal=prediction.get("signal_source"),
        decision="weight_nudge_up" if correct else "weight_nudge_down",
        prediction=prediction.get("statement"),
        judge=expert,
    )


def emit_rotation_tokens_snapshot(tokens: list, changed: bool) -> None:
    """Trail event when rotation-token watchlist snapshot updates soul_map."""
    emit_trail_event(
        "rotation_tokens_update",
        evidence={"tokens": tokens, "state_changed": changed},
        signal="rotation_watchlist",
        decision="conviction_refresh" if changed else "snapshot_only",
    )
