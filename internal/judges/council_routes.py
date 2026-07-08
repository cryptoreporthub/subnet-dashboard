"""
FastAPI APIRouter for the Judge Council endpoints.

Provides:
  GET /api/judges          - Score all subnets through the three-judge council
  GET /api/council         - Full merged data pipeline (Blockmachine + TaoStats + TMC + judges)
  GET /api/paper-portfolio - Paper portfolio for all judges
  GET /api/postmortems     - Postmortems for all judges
  GET /judge-council       - Standalone Judge Council HTML page
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

council_router = APIRouter()

_TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "templates",
)


def _deduplicate_subnets(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate subnets by netuid, keeping the first occurrence."""
    seen = set()
    unique = []
    for sn in subnets:
        nuid = sn.get("netuid", sn.get("id", 0))
        if nuid not in seen:
            seen.add(nuid)
            unique.append(sn)
    return unique


def _get_merged_data():
    """Try to fetch merged subnet data. Returns (merged_list, source_str) or (None, 'none')."""
    try:
        from fetchers.merged_data import get_merged_subnet_data
        merged = get_merged_subnet_data()
        if merged:
            merged = _deduplicate_subnets(merged)
            return merged, "merged"
    except Exception as e:
        logger.warning("Merged data fetch failed: %s", e)
    return None, "none"


@council_router.get("/api/council")
async def api_council():
    """Full merged data pipeline: Blockmachine + TaoStats + TaoMarketCap + judge scores."""
    try:
        merged, source = _get_merged_data()
        if not merged:
            # Fall back to TMC only
            from fetchers.taomarketcap import get_all_subnets
            merged = get_all_subnets()
            merged = _deduplicate_subnets(merged)
            source = "taomarketcap-fallback"

        if not merged:
            return {
                "status": "degraded",
                "subnets": [],
                "judges": [],
                "meta": {"count": 0, "source": "none", "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")},
            }

        # Score through the judge council
        try:
            from internal.judges.subnet_judges import score_all_subnets
            scored = score_all_subnets(merged)
            scored = _deduplicate_subnets(scored)
        except Exception as e:
            logger.warning("Judge scoring in council endpoint failed: %s", e)
            scored = []

        return {
            "status": "success",
            "subnets": merged,
            "judges": scored,
            "meta": {
                "count": len(merged),
                "judged": len(scored) if scored else 0,
                "source": source,
                "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        }
    except Exception as e:
        logger.error("Council API error: %s", e, exc_info=True)
        return {"status": "error", "error": str(e), "subnets": [], "judges": [], "meta": {"count": 0}}


@council_router.get("/api/judges")
async def api_judges():
    """Score ALL subnets with the three-judge council + consensus."""
    try:
        # Try merged data first for richer scoring
        merged, source = _get_merged_data()
        if merged:
            from internal.judges.subnet_judges import score_all_subnets
            result = score_all_subnets(merged)
            result = _deduplicate_subnets(result)
            logger.info("Judges: scored %d unique subnets (source=%s)", len(result), source)
            return {"success": True, "judges": result, "count": len(result), "source": source}

        # Fall back to TMC-only data
        from fetchers.taomarketcap import get_all_subnets
        from internal.judges.subnet_judges import score_all_subnets

        subnets_data = get_all_subnets()
        subnets_data = _deduplicate_subnets(subnets_data)
        if not subnets_data:
            return {"success": False, "error": "No subnet data available", "judges": [], "count": 0}
        result = score_all_subnets(subnets_data)
        result = _deduplicate_subnets(result)
        logger.info("Judges: scored %d unique subnets (source=taomarketcap)", len(result))
        return {"success": True, "judges": result, "count": len(result), "source": "taomarketcap"}
    except Exception as e:
        logger.warning("Judge scoring failed: %s", e, exc_info=True)
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
