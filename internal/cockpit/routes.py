"""Optional GET /api/cockpit/sections — mount via learning_router or server (Agent B)."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from starlette.responses import StreamingResponse

from internal.cockpit.sections import get_cockpit_sections

logger = logging.getLogger(__name__)

cockpit_router = APIRouter(tags=["cockpit"])


def _emitted_at_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _format_snapshot_event(emitted_at: str) -> str:
    payload = get_cockpit_sections()
    data = {
        "type": "cockpit.sections",
        "version": 1,
        "status": payload.get("status", "success"),
        "emitted_at": emitted_at,
        "sections": payload.get("sections", []),
    }
    body = json.dumps(data, separators=(",", ":"))
    return f"retry: 15000\nevent: cockpit.sections\nid: {emitted_at}\ndata: {body}\n\n"


async def _cockpit_stream(request: Request, once: bool):
    emitted_at = _emitted_at_z()
    yield _format_snapshot_event(emitted_at)
    if once:
        return

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
            yield _format_snapshot_event(_emitted_at_z())


@cockpit_router.get("/api/cockpit/sections")
async def api_cockpit_sections():
    """Return all 12 Premium Cockpit sections with live summaries."""
    return get_cockpit_sections()


@cockpit_router.get("/api/cockpit/stream")
async def api_cockpit_stream(
    request: Request,
    once: int | None = Query(None),
):
    """SSE stream of cockpit section snapshots for live hydration."""
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        _cockpit_stream(request, once == 1),
        media_type="text/event-stream",
        headers=headers,
    )
