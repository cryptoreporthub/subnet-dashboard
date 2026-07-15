"""Wire scenario-memory outcomes from resolved predictions (Phase N2)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from internal.council import scenario_memory

logger = logging.getLogger(__name__)


def _outcome_label(prediction: Dict[str, Any]) -> Optional[str]:
    correct = prediction.get("correct")
    if correct is True:
        return "correct"
    if correct is False:
        return "wrong"
    raw = str(prediction.get("outcome") or "").lower()
    if raw in {"hit", "correct", "win"}:
        return "correct"
    if raw in {"miss", "wrong", "loss"}:
        return "wrong"
    return None


def _resolved_predictions() -> List[Dict[str, Any]]:
    try:
        from internal.learning.predictions_store import load_predictions

        data = load_predictions()
    except Exception as exc:
        logger.warning("scenario outcome backfill: predictions load failed: %s", exc)
        return []

    rows: List[Dict[str, Any]] = []
    seen = set()
    for bucket in ("resolved", "predictions"):
        for pred in data.get(bucket, []) or []:
            if not isinstance(pred, dict):
                continue
            pid = pred.get("id")
            if pid and pid in seen:
                continue
            if pid:
                seen.add(pid)
            if pred.get("status") == "resolved" or bucket == "resolved":
                rows.append(pred)
    return rows


def _metadata_from_prediction(prediction: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: v
        for k, v in {
            "prediction_id": prediction.get("id"),
            "actual_pct": prediction.get("actual_pct"),
            "predicted_pct": prediction.get("predicted_pct"),
            "netuid": prediction.get("netuid"),
            "horizon_type": prediction.get("horizon_type"),
            "backfilled": True,
        }.items()
        if v is not None
    }


def backfill_scenario_outcomes_from_predictions() -> Dict[str, int]:
    """Stamp blank scenario rows from resolved predictions (idempotent)."""
    pending_before = _pending_scenario_count()
    if pending_before == 0:
        return {"updated": 0, "pending_before": 0, "pending_after": 0}

    updated = 0
    for pred in _resolved_predictions():
        label = _outcome_label(pred)
        if not label:
            continue
        meta = _metadata_from_prediction(pred)
        sid = pred.get("scenario_id")
        if sid and scenario_memory.update_outcome(str(sid), label, meta):
            updated += 1
            continue
        name = pred.get("name")
        if not name:
            continue
        regime = None
        try:
            regime = scenario_memory.classify_regime(
                {
                    "avg_change_24h": pred.get("actual_pct", 0),
                    "volatility": abs(float(pred.get("actual_pct", 0) or 0)),
                }
            )
        except Exception:
            regime = "neutral"
        result = scenario_memory.record_outcome(
            name=str(name),
            outcome=label,
            features={
                "direction": pred.get("direction"),
                "predicted_pct": pred.get("predicted_pct"),
                "actual_pct": pred.get("actual_pct"),
                "netuid": pred.get("netuid"),
            },
            regime=regime,
            metadata=meta,
            scenario_id=str(sid) if sid else None,
        )
        if result and result.get("outcome"):
            updated += 1

    pending_after = _pending_scenario_count()
    return {
        "updated": updated,
        "pending_before": pending_before,
        "pending_after": pending_after,
    }


def _pending_scenario_count() -> int:
    snap = scenario_memory.get_memory_snapshot()
    return sum(1 for s in snap.get("scenarios", []) if not s.get("outcome"))


def scenario_outcome_stats() -> Dict[str, Any]:
    """Summary for learning stats / API consumers."""
    backfill_scenario_outcomes_from_predictions()
    snap = scenario_memory.get_memory_snapshot()
    scenarios = snap.get("scenarios", []) or []
    resolved = sum(1 for s in scenarios if s.get("outcome"))
    pending = len(scenarios) - resolved
    return {
        "scenario_count": len(scenarios),
        "outcomes_resolved": resolved,
        "outcomes_pending": pending,
        "last_scenario": scenarios[-1].get("name") if scenarios else None,
        "last_outcome": scenarios[-1].get("outcome") if scenarios else None,
        "last_updated": (snap.get("meta") or {}).get("last_updated"),
        "stats": snap.get("stats") or {},
    }
