"""§17.F3 — paper portfolio HTTP routes."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from internal.portfolio.engine import build_portfolio_status

portfolio_router = APIRouter(tags=["portfolio"])


@portfolio_router.get("/api/portfolio/status")
async def api_portfolio_status() -> Dict[str, Any]:
    return build_portfolio_status()
