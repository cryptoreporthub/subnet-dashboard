"""JSON health probe for Fly.io and external monitors (slice 14b)."""

from __future__ import annotations

from fastapi import APIRouter

health_router = APIRouter(tags=["health"])


@health_router.get("/api/health")
async def api_health_check():
    """JSON health probe mirroring plain-text ``/health``."""
    return {"status": "ok"}
