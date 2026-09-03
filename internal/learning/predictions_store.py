"""Read/write helpers for `data/predictions.json`."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PREDICTIONS_PATH = os.path.join("data", "predictions.json")


def load_predictions(*, persist: bool = False) -> Dict[str, Any]:
    try:
        with open(PREDICTIONS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    data.setdefault("predictions", [])
    data.setdefault("resolved", [])
    data.setdefault("stats", {})
    return data


def save_predictions(data: Dict[str, Any], *, caller: Optional[str] = None) -> None:
    """Write predictions.json atomically with caller attribution."""
    try:
        from internal.file_utils import safe_write_json
        safe_write_json(PREDICTIONS_PATH, data)
    except Exception as exc:
        src = caller or "unknown"
        logger.warning("Failed to persist predictions.json (source=%s): %s", src, exc)


def append_prediction(prediction: Dict[str, Any]) -> bool:
    if not isinstance(prediction, dict):
        return False
    data = load_predictions()
    pending = data.setdefault("predictions", [])
    pending.append(prediction)
    save_predictions(data)
    return True


def update_stats(data: Dict[str, Any]) -> None:
    pass


def has_pending_duplicate(netuid: Any, horizon_type: str = "hour", *, shadow: bool = False) -> bool:
    return False


def count_unclassified(data: Optional[Dict[str, Any]] = None) -> int:
    return 0
