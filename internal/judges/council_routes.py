"""
FastAPI APIRouter for the Judge Council endpoints.

Provides:
  GET /api/judges          - Score all subnets through the three-judge council
  GET /api/paper-portfolio - Paper portfolio for all judges
  GET /api/postmortems     - Postmortems for all judges
  GET /judge-council       - Standalone Judge Council HTML page
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

council_router = APIRouter()

_TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "templates",
)


@council_router.get("/api/judges")
async def api_judges():
    """Score all subnets with the three-judge council + consensus."""
    try:
        from fetchers.taomarketcap import get_all_subnets
        from internal.judges.subnet_judges import score_all_subnets

        subnets_data = get_all_subnets()
        if not subnets_data:
            return {"success": False, "error": "No subnet data available", "judges": [], "count": 0}
        result = score_all_subnets(subnets_data)
        return {"success": True, "judges": result, "count": len(result)}
    except Exception as e:
        logger.warning("Judge scoring failed: %s", e)
        return {"success": False, "error": str(e), "judges": [], "count": 0}


@council_router.get("/api/paper-portfolio")
async def api_paper_portfolio():
    """Return aggregate paper portfolio across all judges."""
    try:
        from internal.judges.portfolios import all_portfolios

        portfolios = all_portfolios()
        return {"success": True, "portfolios": portfolios}
    except Exception as e:
        logger.warning("Portfolio fetch failed: %s", e)
        return {"success": False, "error": str(e), "portfolios": {}}


@council_router.get("/api/postmortems")
async def api_postmortems():
    """Return postmortems across all judges."""
    try:
        from internal.judges.postmortems import all_postmortems

        postmortems = all_postmortems()
        return {"success": True, "postmortems": postmortems}
    except Exception as e:
        logger.warning("Postmortem fetch failed: %s", e)
        return {"success": False, "error": str(e), "postmortems": {}}


@council_router.get("/judge-council", response_class=HTMLResponse)
async def judge_council_page():
    """Serve the standalone Judge Council page."""
    path = os.path.join(_TEMPLATES_DIR, "judge_council.html")
    try:
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        return HTMLResponse(content=html)
    except Exception as e:
        logger.warning("Judge council template not found: %s", e)
        return HTMLResponse(content="<h1>Judge Council page not available</h1>", status_code=503)