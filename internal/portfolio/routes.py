"""§17.F3 — paper portfolio HTTP routes."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter

from internal.portfolio.engine import build_portfolio_status
from internal.request_executor import to_thread_timeout

portfolio_router = APIRouter(tags=["portfolio"])
logger = logging.getLogger(__name__)

PORTFOLIO_HANDLER_TIMEOUT = float(os.environ.get("PORTFOLIO_HANDLER_TIMEOUT_SECONDS", "8"))


@portfolio_router.get("/api/portfolio/status")
async def api_portfolio_status() -> Dict[str, Any]:
    try:
        return await to_thread_timeout(
            build_portfolio_status, PORTFOLIO_HANDLER_TIMEOUT, label="portfolio-status"
        )
    except asyncio.TimeoutError:
        return {
            "status": "timeout",
            "error": "timeout",
            "empty": True,
            "benchmark": "hold_tao",
            "summary": {
                "open_positions": 0,
                "total_closed": 0,
                "win_count": 0,
                "loss_count": 0,
                "win_pct": 0.0,
                "total_pnl_pct": 0.0,
                "avg_pnl_pct": 0.0,
                "hold_tao_pnl_pct": 0.0,
            },
            "open_positions": [],
            "closed_positions": [],
            "eligibility": {"source": "data/predictions.json"},
        }
