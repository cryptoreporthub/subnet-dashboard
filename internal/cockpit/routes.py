"""Optional GET /api/cockpit/sections — mount via learning_router or server (Agent B)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from starlette.responses import StreamingResponse

from internal.cockpit.picks_snapshot import build_picks_snapshot, get_stale_picks_snapshot
from internal.cockpit.sections import get_cockpit_sections

logger = logging.getLogger(__name__)

cockpit_router = APIRouter(tags=["cockpit"])

_PICKS_BUILD_TIMEOUT = float(os.environ.get("COCKPIT_PICKS_TIMEOUT", "8"))
_SECTIONS_BUILD_TIMEOUT = float(os.environ.get("COCKPIT_SECTIONS_TIMEOUT", "8"))


def _emitted_at_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def _build_sections_payload() -> dict:
    # get_cockpit_sections() -> _build_council_picks() -> select_hourly_pick()
    # scores the full subnet universe synchronously. A live py-spy dump caught
    # this exact call (via the SSE stream below) holding the event loop in
    # production — dispatch off-thread with a bounded wait, same pattern as
    # _build_picks_payload() above.
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(get_cockpit_sections),
            timeout=_SECTIONS_BUILD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("cockpit.sections build timed out after %.1fs", _SECTIONS_BUILD_TIMEOUT)
        return {"status": "timeout", "sections": []}


async def _format_sections_event(emitted_at: str) -> str:
    payload = await _build_sections_payload()
    data = {
        "type": "cockpit.sections",
        "version": 1,
        "status": payload.get("status", "success"),
        "emitted_at": emitted_at,
        "sections": payload.get("sections", []),
    }
    body = json.dumps(data, separators=(",", ":"))
    return f"event: cockpit.sections\nid: {emitted_at}\ndata: {body}\n\n"


async def _build_picks_payload() -> dict:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(build_picks_snapshot),
            timeout=_PICKS_BUILD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("cockpit.picks build timed out after %.1fs", _PICKS_BUILD_TIMEOUT)
        stale = get_stale_picks_snapshot()
        if stale:
            stale = dict(stale)
            stale["emitted_at"] = _emitted_at_z()
            stale["status"] = "stale"
            return stale
        return {
            "type": "cockpit.picks",
            "version": 1,
            "emitted_at": _emitted_at_z(),
            "status": "timeout",
            "hour": {"picks": [], "meta": {"quiet_reason": "Hour watch delayed — retry shortly"}},
            "day": {"action": "HOLD", "published": False, "reason": "snapshot timeout"},
        }


def _format_picks_event(data: dict, emitted_at: str) -> str:
    data = dict(data)
    data["emitted_at"] = data.get("emitted_at") or emitted_at
    body = json.dumps(data, separators=(",", ":"))
    return f"event: cockpit.picks\nid: {emitted_at}\ndata: {body}\n\n"


async def _cockpit_stream(request: Request, once: bool):
    yield f"retry: 15000\n"
    yield f": open {_emitted_at_z()}\n\n"
    emitted_at = _emitted_at_z()
    picks = await _build_picks_payload()
    yield _format_picks_event(picks, emitted_at)
    if once:
        return
    yield await _format_sections_event(emitted_at)

    elapsed = 0
    while True:
        if await request.is_disconnected():
            break
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            break
        elapsed += 1
        if elapsed % 15 == 0:
            yield f": heartbeat {_emitted_at_z()}\n\n"
        if elapsed % 60 == 0:
            picks = await _build_picks_payload()
            yield _format_picks_event(picks, _emitted_at_z())
        if elapsed % 300 == 0:
            yield await _format_sections_event(_emitted_at_z())


@cockpit_router.get("/api/cockpit/sections")
async def api_cockpit_sections():
    """Return all 12 Premium Cockpit sections with live summaries."""
    return await _build_sections_payload()


@cockpit_router.get("/api/cockpit/stream")
async def api_cockpit_stream(
    request: Request,
    once: int | None = Query(None),
):
    """SSE stream: cockpit.picks every 60s, cockpit.sections every 300s."""
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        _cockpit_stream(request, once == 1),
        media_type="text/event-stream",
        headers=headers,
    )
