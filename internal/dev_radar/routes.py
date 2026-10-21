"""Dev Pulse API routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from internal.dev_radar.service import build_dev_radar_payload

dev_radar_router = APIRouter(tags=["dev-radar"])


@dev_radar_router.get("/api/dev-radar")
async def api_dev_radar(limit: Optional[int] = Query(None, ge=1)):
    """Registry github URLs + graded ledger snippet per subnet."""
    return build_dev_radar_payload(limit=limit)
