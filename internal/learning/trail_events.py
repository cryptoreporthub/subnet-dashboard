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
    resolved_prediction_id: Any = None,
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

        MindmapBridge(persistence_path=SOUL_MAP_PATH).append_learning_trail(
            entry, resolved_prediction_id=resolved_prediction_id
        )
    except Exception as exc:
        logger.warning("Trail event %s failed: %s", event_type, exc)


def _prediction_resolved_recorded(prediction_id: Any) -> bool:
    """True when this prediction's resolution is already on record.

    The resolved-id ledger never truncates, so it outlives the trail window. The trail scan
    covers rows written before the ledger existed.
    """
    from internal.council.mindmap_bridge import MindmapBridge, pending_resolved_ids
    from internal.council.weights import SOUL_MAP_PATH

    # A row whose disk write failed is buffered until a write carries it. Check the buffer first.
    if prediction_id in pending_resolved_ids(SOUL_MAP_PATH):
        return True
    state = MindmapBridge(persistence_path=SOUL_MAP_PATH).soul_map_state
    ledger = state.get("resolved_prediction_ids")
    if isinstance(ledger, list) and prediction_id in ledger:
        return True
    trail = state.get("learning_trail") or []
    for e in trail:
        if not isinstance(e, dict) or e.get("event_type") != "prediction_resolved":
            continue
        evidence = e.get("evidence")
        # Legacy rows may carry non-dict evidence; they cannot match, and must not raise.
        if isinstance(evidence, dict) and evidence.get("prediction_id") == prediction_id:
            return True
    return False


def emit_prediction_resolved(prediction: Dict[str, Any], expert: Optional[str]) -> None:
    """Trail event when a prediction resolves and nudges expert weights."""
    prediction_id = prediction.get("id")
    if prediction_id is not None and _prediction_resolved_recorded(prediction_id):
        # Replayed resolution: already on record, so emit nothing.
        return
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
        resolved_prediction_id=prediction_id,
    )


def emit_rotation_tokens_snapshot(tokens: list, changed: bool) -> None:
    """Trail event when rotation-token watchlist snapshot updates soul_map."""
    emit_trail_event(
        "rotation_tokens_update",
        evidence={"tokens": tokens, "state_changed": changed},
        signal="rotation_watchlist",
        decision="conviction_refresh" if changed else "snapshot_only",
    )
