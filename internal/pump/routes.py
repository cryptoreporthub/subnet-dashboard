"""Optional read routes for pump ladder state (Phase D Agent A)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from internal.api_errors import public_error
from internal.pump.pattern_ledger import active_patterns, pattern_payload
from internal.pump.scheduler import ensure_pump_ladder_scheduler, get_pump_ladder_scheduler_state
from internal.pump.state import get_ladder_snapshot, scan_all_subnets
from internal.pump.summary import summarize_pump
from internal.rate_limit import limit_or_noop, strict_limit

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
@limit_or_noop(strict_limit(), override_defaults=True)
async def api_pump_ladder_scan(request: Request):
    ensure_pump_ladder_scheduler(immediate=False)
    try:
        return scan_all_subnets()
    except Exception as exc:
        logger.warning("pump ladder manual scan failed: %s", exc)
        return {"ok": False, **public_error(exc, code="pump_scan_failed")}


@pump_ladder_router.get("/api/pump-patterns/active")
async def api_pump_patterns_active():
    ensure_pump_ladder_scheduler(immediate=False)
    return {"items": active_patterns()}


@pump_ladder_router.get("/api/pump-patterns/{netuid}")
async def api_pump_patterns_netuid(netuid: int):
    ensure_pump_ladder_scheduler(immediate=False)
    return pattern_payload(netuid)
