"""Wire scenario-memory outcomes from resolved predictions (Phase N2 / §16.1)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from internal.council import scenario_memory

logger = logging.getLogger(__name__)

_SKIP_OUTCOMES = frozenset({"duplicate", "expired", "ungradeable"})


def _outcome_label(prediction: Dict[str, Any]) -> Optional[str]:
    if prediction.get("outcome") in _SKIP_OUTCOMES:
        return None
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


def _load_prediction_buckets() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    try:
        from internal.learning.predictions_store import load_predictions

        data = load_predictions()
    except Exception as exc:
        logger.warning("scenario outcome backfill: predictions load failed: %s", exc)
        return [], []

    resolved: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
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
            status = pred.get("status")
            if status == "resolved" or bucket == "resolved":
                resolved.append(pred)
            elif status in (None, "pending"):
                pending.append(pred)
    return resolved, pending


def _resolved_predictions() -> List[Dict[str, Any]]:
    resolved, _ = _load_prediction_buckets()
    return resolved


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


def _pending_scenarios() -> List[Dict[str, Any]]:
    snap = scenario_memory.get_memory_snapshot()
    return [s for s in (snap.get("scenarios") or []) if not s.get("outcome")]


def _netuid_of(scenario: Dict[str, Any]) -> Any:
    feats = scenario.get("features") or {}
    meta = scenario.get("metadata") or {}
    return feats.get("netuid", meta.get("netuid"))


def _stamp_pending_from_prediction(pred: Dict[str, Any], label: str) -> bool:
    """Stamp an existing blank scenario; never mint a new row during backfill."""
    meta = _metadata_from_prediction(pred)
    sid = pred.get("scenario_id")
    if sid and scenario_memory.update_outcome(str(sid), label, meta):
        return True

    pending = _pending_scenarios()
    if not pending:
        return False

    pid = pred.get("id")
    name = pred.get("name")
    netuid = pred.get("netuid")

    # 1) metadata.prediction_id already linked
    if pid:
        for s in reversed(pending):
            if (s.get("metadata") or {}).get("prediction_id") == pid:
                return bool(scenario_memory.update_outcome(str(s["id"]), label, meta))

    # 2) name + netuid (regime-agnostic — fixes N2 regime-mismatch gap)
    if name is not None and netuid is not None:
        for s in reversed(pending):
            if s.get("name") == name and _netuid_of(s) == netuid:
                return bool(scenario_memory.update_outcome(str(s["id"]), label, meta))

    # 3) name only
    if name is not None:
        for s in reversed(pending):
            if s.get("name") == name:
                return bool(scenario_memory.update_outcome(str(s["id"]), label, meta))

    return False


def _preds_link_scenario(
    scenario: Dict[str, Any],
    preds: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    sid = scenario.get("id")
    name = scenario.get("name")
    netuid = _netuid_of(scenario)
    meta_pid = (scenario.get("metadata") or {}).get("prediction_id")
    linked: List[Dict[str, Any]] = []
    for p in preds:
        if sid and p.get("scenario_id") == sid:
            linked.append(p)
            continue
        if meta_pid and p.get("id") == meta_pid:
            linked.append(p)
            continue
        if name is not None and p.get("name") == name and (
            netuid is None or p.get("netuid") == netuid
        ):
            linked.append(p)
    return linked


def _classify_unresolvable(
    scenario: Dict[str, Any],
    resolved: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Caller already excluded scenarios still awaiting an open prediction."""
    sid = scenario.get("id")
    name = scenario.get("name")
    linked = _preds_link_scenario(scenario, resolved)
    if not linked:
        return {
            "scenario_id": sid,
            "name": name,
            "reason": "no_matching_prediction",
        }

    for p in linked:
        if _outcome_label(p):
            return {
                "scenario_id": sid,
                "name": name,
                "reason": "match_failed",
                "prediction_id": p.get("id"),
            }
        if p.get("outcome") in _SKIP_OUTCOMES:
            return {
                "scenario_id": sid,
                "name": name,
                "reason": "prediction_ungradeable",
                "prediction_id": p.get("id"),
                "outcome": p.get("outcome"),
            }
        return {
            "scenario_id": sid,
            "name": name,
            "reason": "prediction_missing_grade",
            "prediction_id": p.get("id"),
        }

    return {
        "scenario_id": sid,
        "name": name,
        "reason": "no_matching_prediction",
    }


def _scenario_awaiting_prediction(
    scenario: Dict[str, Any],
    pending_preds: List[Dict[str, Any]],
) -> bool:
    return bool(_preds_link_scenario(scenario, pending_preds))


def list_unresolvable_scenarios() -> List[Dict[str, Any]]:
    """Pending scenarios that cannot be stamped from current prediction store."""
    resolved, pending_preds = _load_prediction_buckets()
    out: List[Dict[str, Any]] = []
    for s in _pending_scenarios():
        if _scenario_awaiting_prediction(s, pending_preds):
            continue
        out.append(_classify_unresolvable(s, resolved))
    return out


def backfill_scenario_outcomes_from_predictions() -> Dict[str, Any]:
    """Stamp blank scenario rows from resolved predictions (idempotent).

    Only updates existing pending scenarios — does not mint duplicate outcome rows.
    """
    pending_before = _pending_scenario_count()
    if pending_before == 0:
        return {
            "updated": 0,
            "pending_before": 0,
            "pending_after": 0,
            "unresolvable_count": 0,
        }

    updated = 0
    for pred in _resolved_predictions():
        label = _outcome_label(pred)
        if not label:
            continue
        if _stamp_pending_from_prediction(pred, label):
            updated += 1

    pending_after = _pending_scenario_count()
    unresolvable = list_unresolvable_scenarios()
    return {
        "updated": updated,
        "pending_before": pending_before,
        "pending_after": pending_after,
        "unresolvable_count": len(unresolvable),
        "unresolvable": unresolvable[:50],
    }


def _pending_scenario_count() -> int:
    return len(_pending_scenarios())


def scenario_outcome_stats() -> Dict[str, Any]:
    """Summary for learning stats / API consumers."""
    backfill = backfill_scenario_outcomes_from_predictions()
    snap = scenario_memory.get_memory_snapshot()
    scenarios = snap.get("scenarios", []) or []
    resolved = sum(1 for s in scenarios if s.get("outcome"))
    pending = len(scenarios) - resolved
    unresolvable = backfill.get("unresolvable") or list_unresolvable_scenarios()
    return {
        "scenario_count": len(scenarios),
        "outcomes_resolved": resolved,
        "outcomes_pending": pending,
        "unresolvable_count": len(unresolvable),
        "unresolvable": unresolvable[:50],
        "last_scenario": scenarios[-1].get("name") if scenarios else None,
        "last_outcome": scenarios[-1].get("outcome") if scenarios else None,
        "last_updated": (snap.get("meta") or {}).get("last_updated"),
        "stats": snap.get("stats") or {},
    }
