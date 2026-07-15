"""Read/write helpers for ``data/predictions.json``."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

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


def _migrate_phases(data: Dict[str, Any]) -> bool:
    changed = False
    for bucket in ("predictions", "resolved"):
        for pred in data.get(bucket, []) or []:
            phase = pred.get("phase_at_prediction")
            if phase in _V1_TO_V2_PHASE:
                pred["phase_at_prediction"] = _V1_TO_V2_PHASE[phase]
                changed = True
    return changed


def load_predictions() -> Dict[str, Any]:
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
    if _migrate_phases(data):
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


def has_pending_duplicate(netuid: Any, horizon_type: str = "hour") -> bool:
    """True when a pending row already exists for netuid + horizon."""
    if netuid is None:
        return False
    for existing in load_predictions().get("predictions", []) or []:
        if (
            existing.get("netuid") == netuid
            and existing.get("horizon_type", "hour") == horizon_type
            and existing.get("status") == "pending"
        ):
            return True
    return False


def append_prediction(prediction: Dict[str, Any]) -> bool:
    """Append a pending prediction if no duplicate is already pending.

    Duplicate key: same ``netuid`` + ``horizon_type`` while status is pending.
    Returns True when the prediction was stored.
    """
    if not isinstance(prediction, dict):
        return False
    netuid = prediction.get("netuid")
    horizon_type = prediction.get("horizon_type", "hour")
    if netuid is None:
        return False

    data = load_predictions()
    pending = data.get("predictions", [])
    for existing in pending:
        if (
            existing.get("netuid") == netuid
            and existing.get("horizon_type", "hour") == horizon_type
            and existing.get("status") == "pending"
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
    correct = sum(1 for row in resolved if row.get("correct"))
    wrong = sum(1 for row in resolved if not row.get("correct"))
    stats = {
        "correct": correct,
        "wrong": wrong,
        "pending": len(preds),
        "total": len(preds) + len(resolved),
    }
    if correct + wrong > 0:
        stats["accuracy"] = round(correct / (correct + wrong), 3)
    else:
        stats["accuracy"] = 0.0
    data["stats"] = stats
