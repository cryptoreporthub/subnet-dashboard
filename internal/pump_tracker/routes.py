"""FastAPI read routes for /api/pump-tracker/* (mounted via learning_router)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from internal.pump_tracker.adapter import (
    PumpEngineUnavailable,
    get_ladder_snapshot,
    get_top_movers,
    subnets_for_phase,
)
from internal.pump_tracker.summary import summarize_pump_tracker

logger = logging.getLogger(__name__)

pump_tracker_router = APIRouter(tags=["pump-tracker"])


def _unavailable_payload(exc: Exception) -> dict:
    return {
        "status": "unavailable",
        "error": f"pump engine unavailable: {exc}",
        "subnets": [],
        "movers": [],
    }


@pump_tracker_router.get("/api/pump-tracker/ladder")
async def api_pump_tracker_ladder():
    """All subnets with current pump ladder phase."""
    try:
        return get_ladder_snapshot()
    except PumpEngineUnavailable as exc:
        return _unavailable_payload(exc)
    except Exception as exc:
        logger.warning("pump-tracker ladder failed: %s", exc)
        return {"status": "error", "error": str(exc), "subnets": []}


@pump_tracker_router.get("/api/pump-tracker/phase/{phase}")
async def api_pump_tracker_phase(phase: str):
    """Subnets currently in a given pump phase."""
    try:
        return subnets_for_phase(phase)
    except PumpEngineUnavailable as exc:
        payload = _unavailable_payload(exc)
        payload["phase"] = phase.upper()
        return payload
    except Exception as exc:
        logger.warning("pump-tracker phase filter failed: %s", exc)
        return {"status": "error", "phase": phase.upper(), "subnets": [], "error": str(exc)}


@pump_tracker_router.get("/api/pump-tracker/top-movers")
async def api_pump_tracker_top_movers(limit: int = Query(default=20, ge=1, le=100)):
    """Biggest recent pump phase transitions."""
    try:
        return get_top_movers(limit=limit)
    except PumpEngineUnavailable as exc:
        return _unavailable_payload(exc)
    except Exception as exc:
        logger.warning("pump-tracker top-movers failed: %s", exc)
        return {"status": "error", "movers": [], "error": str(exc)}


@pump_tracker_router.get("/api/pump-tracker/summary")
async def api_pump_tracker_summary():
    """Panel summary (also folded into /api/mindmap/state)."""
    return {"status": "success", "summary": summarize_pump_tracker()}
