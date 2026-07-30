"""Dev Pulse API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from internal.dev_radar.service import build_dev_radar_payload

dev_radar_router = APIRouter(tags=["dev-radar"])


@dev_radar_router.get("/api/dev-radar")
async def api_dev_radar(limit: int = Query(128, ge=1, le=256)):
    """Registry github URLs + graded ledger snippet per subnet."""
    return build_dev_radar_payload(limit=limit)
