Title: 

URL Source: https://raw.githubusercontent.com/cryptoreporthub/subnet-dashboard/main/internal/health/routes.py

Markdown Content:
"""JSON health probe for Fly.io and external monitors (slice 14b)."""

from __future__ import annotations

from fastapi import APIRouter

health_router = APIRouter(tags=["health"])

@health_router.get("/api/data-freshness")
async def api_data_freshness():
    """Live-data freshness for the on-chain feed (audit finding #1)."""
    from internal.live_subnets import live_data_freshness
    return live_data_freshness()


@health_router.get("/api/health")
async def api_health_check():
    """JSON health probe mirroring plain-text ``/health``."""
    return {"status": "ok"}
