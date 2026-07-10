"""FastAPI read routes for pump analytics and price tracking (slice 10b)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

analytics_router = APIRouter(tags=["analytics"])

PRICE_BASELINE_FILE = os.environ.get("PRICE_BASELINE_FILE", "data/price_baselines.json")


def _empty_pump_payload() -> Dict[str, Any]:
    return {
        "status": "error",
        "data": {
            "subnets": [],
            "meta": {
                "tracked_subnets": 0,
                "total_cycles": 0,
                "avg_proneness": 0.0,
                "top_pump_candidates": [],
                "updated_at": None,
            },
        },
    }


@analytics_router.get("/api/pump-analytics")
async def api_pump_analytics(netuid: Optional[int] = Query(default=None)):
    """Return pump cycle analytics for all subnets or one via ``?netuid=``."""
    try:
        from internal.pump_tracker import get_pump_tracker

        tracker = get_pump_tracker()
        if tracker is None:
            return _empty_pump_payload()
        data = tracker.get_all_analytics()
        if netuid is not None:
            subnets = [
                s for s in data["data"]["subnets"] if s.get("netuid") == netuid
            ]
            data["data"]["subnets"] = subnets
            data["data"]["meta"]["tracked_subnets"] = len(subnets)
        return data
    except Exception as exc:
        logger.warning("pump-analytics failed: %s", exc)
        payload = _empty_pump_payload()
        payload["error"] = str(exc)
        return payload


@analytics_router.get("/api/price-tracking/baselines")
async def api_price_tracking_baselines():
    """Return recorded baseline price history for tracked subnets."""
    try:
        if not os.path.exists(PRICE_BASELINE_FILE):
            return {
                "status": "success",
                "meta": {"count": 0, "source": "file"},
                "baselines": [],
            }
        with open(PRICE_BASELINE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            data = []
        netuids = {e.get("netuid") for e in data if e.get("netuid") is not None}
        return {
            "status": "success",
            "meta": {
                "count": len(data),
                "tracked_subnets": len(netuids),
                "source": "file",
            },
            "baselines": data,
        }
    except Exception as exc:
        logger.warning("price-tracking/baselines failed: %s", exc)
        return {"status": "error", "error": str(exc), "baselines": []}


@analytics_router.get("/api/price-tracking/outcomes")
async def api_price_tracking_outcomes():
    """Return recorded price outcomes (empty when message-intel DB unavailable)."""
    try:
        from message_intel.models import MessageIntelDB

        db = MessageIntelDB()
        outcomes: List[Dict[str, Any]] = db.list_price_outcomes(limit=100)
        return {
            "status": "success",
            "meta": {"count": len(outcomes)},
            "outcomes": outcomes,
        }
    except Exception as exc:
        logger.warning("price-tracking/outcomes unavailable: %s", exc)
        return {"status": "success", "meta": {"count": 0}, "outcomes": []}
