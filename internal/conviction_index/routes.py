"""FastAPI routes for Telegram Conviction Index (/api/conviction-index/*)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal

from fastapi import APIRouter, Query
from starlette.concurrency import run_in_threadpool

from internal.conviction_index import (
    build_leaderboard,
    get_conviction_snapshot,
    health_payload,
    populate_author_reliability,
)

logger = logging.getLogger(__name__)

conviction_index_router = APIRouter(tags=["conviction-index"])


@conviction_index_router.get("/api/conviction-index")
async def api_conviction_index(refresh: bool = Query(default=False)) -> Dict[str, Any]:
    """Top-5 subnets by conviction index plus full per-subnet scores."""
    try:
        state = await run_in_threadpool(get_conviction_snapshot, refresh=refresh)
        return {
            "status": "ok",
            "top5": state.get("top5") or [],
            "subnets": state.get("subnets") or {},
            "updated_at": state.get("updated_at"),
        }
    except Exception as exc:
        logger.error("conviction-index snapshot failed: %s", exc)
        return {
            "status": "error",
            "top5": [],
            "subnets": {},
            "error": str(exc),
        }


@conviction_index_router.get("/api/conviction-index/health")
async def api_conviction_index_health() -> Dict[str, Any]:
    return await run_in_threadpool(health_payload)


@conviction_index_router.get("/api/conviction-leaderboard")
async def api_conviction_leaderboard(
    days: Literal[7, 30, 90] = Query(default=30),
) -> Dict[str, Any]:
    """Caller leaderboard — fade accuracy tracked separately from long accuracy."""
    try:
        await run_in_threadpool(populate_author_reliability, lookback_days=days)
        board = await run_in_threadpool(build_leaderboard, days=days)
        return {"status": "ok", **board}
    except Exception as exc:
        logger.error("conviction-leaderboard failed: %s", exc)
        return {"status": "error", "authors": [], "error": str(exc)}
