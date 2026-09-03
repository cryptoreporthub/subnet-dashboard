"""Read/write helpers for ``data/predictions.json``."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PREDICTIONS_PATH = os.path.join("data", "predictions.json")

_V1_TO_V2_PHASE = {
    "ACCUMULATION": "EARLY",
    "MARKUP": "EARLY",
    "PARABOLIC": "SELL",
    "DISTRIBUTION": "SELL",
    "DECLINE": "INACTIVE",
    "RE_ACCUMULATION": "CONSOLIDATING",
}


def _default_data() -> Dict[str, Any]:
    return {
        "predictions": [],
        "resolved": [],
        "stats": {"correct": 0, "wrong": 0, "pending": 0, "total": 0, "accuracy": 0.0},
    }


def _normalize_prediction_timestamps(prediction: Dict[str, Any]) -> None:
    """Store prediction timestamps in one canonical UTC ISO-8601 format.

    Some older pick payloads contain ``...+00:00Z``.  It is readable once the
    trailing marker is handled correctly, but is not valid input for parsers
    that blindly replace ``Z`` with another offset.
    """
    for key in ("created_at", "resolve_at"):
        value = prediction.get(key)
        if value is None:
            continue
        raw = str(value).strip()
        if raw[-1:].upper() == "Z":
            raw = raw[:-1]
        try:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            prediction[key] = parsed.astimezone(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
        except (TypeError, ValueError):
            # Preserve genuinely corrupt values so the resolver can retire
            # them explicitly instead of silently changing their meaning.
            continue


def _migrate_expert_labels(data: Dict[str, Any]) -> bool:
    """Rename legacy contrarian expert labels to dark_horse."""
    changed = False
    for bucket in ("predictions", "resolved"):
        for pred in data.get(bucket, []) or []:
            expert = pred.get("expert")
            if isinstance(expert, str) and expert.lower().strip() == "contrarian":
                pred["expert"] = "dark_horse"
                changed = True
    return changed


def _migrate_phases(data: Dict[str, Any]) -> bool:
    changed = False
    for bucket in ("predictions", "resolved"):
        for pred in data.get(bucket, []) or []:
            phase = pred.get("phase_at_prediction")
            if phase in _V1_TO_V2_PHASE:
                pred["phase_at_prediction"] = _V1_TO_V2_PHASE[phase]
                changed = True
    return changed


def _migrate_evidence(data: Dict[str, Any]) -> bool:
    from internal.learning.evidence import stamp_evidence

    changed = False
    for bucket in ("predictions", "resolved"):
        for pred in data.get(bucket, []) or []:
            changed = stamp_evidence(pred) or changed
    return changed


def load_predictions(*, persist: bool = False) -> Dict[str, Any]:
    try:
        with open(PREDICTIONS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return _default_data()
    if not isinstance(data, dict):
        return _default_data()
    data.setdefault("predictions", [])
    data.setdefault("resolved", [])
    data.setdefault("stats", _default_data()["stats"])
    changed = _migrate_phases(data)
    changed = _migrate_expert_labels(data) or changed
    changed = _migrate_evidence(data) or changed
    if changed and persist:
        save_predictions(data)
    return data


def save_predictions(data: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(PREDICTIONS_PATH) or ".", exist_ok=True)
        tmp = PREDICTIONS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(tmp, PREDICTIONS_PATH)
    except Exception as exc:
        logger.warning("Failed to persist predictions.json: %s", exc)


def has_pending_duplicate(netuid: Any, horizon_type: str = "hour", *, shadow: bool = False) -> bool:
    """True when a pending row already exists for netuid + horizon (+ shadow flag).""
    if netuid is None:
        return False
    want_shadow = bool(shadow)
    for existing in load_predictions().get("predictions", []) or []:
        if (
            existing.get("netuid") == netuid
            and existing.get("horizon_type", "hour") == horizon_type
            and existing.get("status") == "pending"
            and bool(existing.get("shadow") or existing.get("counterfactual")) == want_shadow
        ):
            return True
    return False


def append_prediction(prediction: Dict[str, Any]) -> bool:
    """Append a pending prediction if no duplicate is already pending.

    Duplicate key: same ``netuid`` + ``horizon_type`` + shadow flag while pending.
    Returns True when the prediction was stored.
    """
    if not isinstance(prediction, dict):
        return False
    from internal.learning.evidence import stamp_evidence

    _normalize_prediction_timestamps(prediction)
    stamp_evidence(prediction)
    netuid = prediction.get("netuid")
    horizon_type = prediction.get("horizon_type", "hour")
    if netuid is None:
        return False
    shadow = bool(prediction.get("shadow") or prediction.get("counterfactual"))

    data = load_predictions()
    pending = data.get("predictions", [])
    for existing in pending:
        if (
            existing.get("netuid") == netuid
            and existing.get("horizon_type", "hour") == horizon_type
            and existing.get("status") == "pending"
            and bool(existing.get("shadow") or existing.get("counterfactual")) == shadow
        ):
            return False

    pending.append(prediction)
    data["predictions"] = pending
    update_stats(data)
    save_predictions(data)
    return True


def update_stats(data: Dict[str, Any]) -> None:
    preds: List[Dict[str, Any]] = data.get("predictions", [])
    resolved: List[Dict[str, Any]] = data.get("resolved", [])

    def _primary(row: Dict[str, Any]) -> bool:
        return not bool(row.get("shadow") or row.get("counterfactual"))

    primary_resolved = [row for row in resolved if _primary(row)]
    primary_pending = [row for row in preds if _primary(row)]
    correct = sum(1 for row in primary_resolved if row.get("correct") is True)
    wrong = sum(1 for row in primary_resolved if row.get("correct") is False)
    stats = {
        "correct": correct,
        "wrong": wrong,
        "pending": len(primary_pending),
        "total": len(primary_pending) + len(primary_resolved),
    }
    if correct + wrong > 0:
        stats["accuracy"] = round(correct / (correct + wrong), 3)
    else:
        stats["accuracy"] = 0.0
    data["stats"] = stats


def count_unclassified(data: Optional[Dict[str, Any]] = None) -> int:
    """Count ledger rows tagged expert=unclassified (pending + resolved).""
    if data is None:
        data = load_predictions()
    if not isinstance(data, dict):
        return 0
    n = 0
    for bucket in ("predictions", "resolved"):
        for row in data.get(bucket) or []:
            if isinstance(row, dict) and str(row.get("expert") or "").lower() == "unclassified":
                n += 1
    return n
