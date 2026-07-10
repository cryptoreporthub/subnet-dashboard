"""Pick-of-the-Hour outcome tracking + success metric (read API support)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

PICK_HISTORY_PATH = os.environ.get("PICK_HISTORY_PATH", os.path.join("data", "pick_history.json"))


def _load() -> Dict[str, Any]:
    try:
        with open(PICK_HISTORY_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            data.setdefault("active", None)
            data.setdefault("history", [])
            return data
    except Exception:
        pass
    return {"active": None, "history": []}


def get_history(limit: int = 20) -> Dict[str, Any]:
    """Return the active pick, recent finalized history, and aggregate stats."""
    store = _load()
    history: List[Dict[str, Any]] = list(store.get("history") or [])
    finalized = [row for row in history if isinstance(row, dict)]
    total = len(finalized)
    wins = sum(1 for row in finalized if row.get("success"))
    success_rate = round(wins / total * 100.0, 1) if total else 0.0
    return {
        "active": store.get("active"),
        "history": finalized[:limit],
        "stats": {
            "total": total,
            "wins": wins,
            "losses": total - wins,
            "success_rate": success_rate,
        },
    }
