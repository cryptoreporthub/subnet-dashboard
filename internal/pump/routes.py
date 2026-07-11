"""Optional read routes for pump ladder state (Phase D Agent A)."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from internal.pump.scheduler import ensure_pump_ladder_scheduler, get_pump_ladder_scheduler_state
from internal.pump.state import get_ladder_snapshot, scan_all_subnets
from internal.pump.summary import summarize_pump

logger = logging.getLogger(__name__)

pump_ladder_router = APIRouter(tags=["pump-ladder"])


@pump_ladder_router.get("/api/pump-ladder/state")
async def api_pump_ladder_state():
    ensure_pump_ladder_scheduler(immediate=False)
    payload = get_ladder_snapshot()
    payload["summary"] = summarize_pump()
    payload["scheduler"] = get_pump_ladder_scheduler_state()
    return payload


@pump_ladder_router.post("/api/pump-ladder/scan")
async def api_pump_ladder_scan():
    ensure_pump_ladder_scheduler(immediate=False)
    try:
        return scan_all_subnets()
    except Exception as exc:
        logger.warning("pump ladder manual scan failed: %s", exc)
        return {"ok": False, "error": str(exc)}
