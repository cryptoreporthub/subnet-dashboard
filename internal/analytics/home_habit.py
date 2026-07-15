"""§17.F1/F2 — SSR snapshots for home watchlist + conviction alert UI."""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def watchlist_snapshot() -> Dict[str, Any]:
    try:
        from internal.watchlist.store import load_watchlist

        data = load_watchlist()
        netuids = data.get("netuids") or []
        return {
            "status": "ok",
            "netuids": netuids,
            "count": len(netuids),
            "updated_at": data.get("updated_at"),
        }
    except Exception as exc:
        logger.warning("watchlist snapshot failed: %s", exc)
        return {"status": "error", "netuids": [], "count": 0, "updated_at": None}


def conviction_alerts_snapshot() -> Dict[str, Any]:
    try:
        from internal.conviction_alerts.evaluate import get_last_run_status

        payload = get_last_run_status()
        enabled = bool(payload.get("enabled"))
        return {
            "status": "ok",
            "enabled": enabled,
            "delivery_mode": payload.get("delivery_mode", "off"),
            "min_confidence": payload.get("min_confidence"),
            "last_run": payload.get("last_run") or {},
        }
    except Exception as exc:
        logger.warning("conviction alerts snapshot failed: %s", exc)
        return {
            "status": "error",
            "enabled": False,
            "delivery_mode": "off",
            "last_run": {},
        }
