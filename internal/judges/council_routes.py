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

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

council_router = APIRouter()

JUDGES_SCORING_UNIVERSE = int(os.environ.get("JUDGES_SCORING_UNIVERSE", "50"))

_TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "templates",
)


def _cap_subnets_for_judges(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Score only the top-emission subnets so hydration cannot starve /health."""
    if not subnets or len(subnets) <= JUDGES_SCORING_UNIVERSE:
        return subnets
    return sorted(
        subnets,
        key=lambda s: float(s.get("emission", 0) or 0),
        reverse=True,
    )[:JUDGES_SCORING_UNIVERSE]


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


def _get_subnets_for_scoring() -> tuple[List[Dict[str, Any]], str]:
    """Return deduped subnets for judge scoring via shared council feed (§30-10)."""
    try:
        from internal.subnets.feed import get_council_subnet_feed

        subnets, source = get_council_subnet_feed()
        subnets = _deduplicate_subnets(subnets)
        if subnets:
            return subnets, source
    except Exception as e:
        logger.warning("Council subnet feed failed: %s", e)
    return [], "none"


def _aggregate_portfolios(portfolios: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate judge portfolios (matches dashboard + other router work)."""
    return {
        "open_positions": sum(
            int((p.get("summary") or {}).get("open_positions", 0) or 0)
            for p in portfolios.values()
            if isinstance(p, dict)
        ),
        "total_closed": sum(
            int((p.get("summary") or {}).get("total_closed", 0) or 0)
            for p in portfolios.values()
            if isinstance(p, dict)
        ),
        "total_pnl_pct": round(
            sum(
                float((p.get("summary") or {}).get("total_pnl_pct", 0) or 0)
                for p in portfolios.values()
                if isinstance(p, dict)
            ),
            4,
        ),
    }


def _score_all_judges(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from internal.judges.subnet_judges import score_all_subnets

    return _deduplicate_subnets(score_all_subnets(subnets))


@council_router.get("/api/council")
async def api_council():
    """Full merged data pipeline: Blockmachine + TaoStats + TaoMarketCap + judge scores."""
    return await asyncio.to_thread(_api_council_sync)


def _api_council_sync():
    try:
        merged, source = _get_subnets_for_scoring()
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

        merged = _cap_subnets_for_judges(merged)

        # Score through the judge council
        try:
            scored = _score_all_judges(merged)
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
    return await asyncio.to_thread(_api_judges_sync)


def _api_judges_sync():
    try:
        subnets, source = _get_subnets_for_scoring()
        if subnets:
            subnets = _cap_subnets_for_judges(subnets)
            result = _score_all_judges(subnets)
            logger.info("Judges: scored %d unique subnets (source=%s)", len(result), source)
            return {
                "success": True,
                "judges": result,
                "count": len(result),
                "source": source,
                "meta": {
                    "count": len(result),
                    "degraded_sources": [],
                    "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            }

        return {"success": False, "error": "No subnet data available", "judges": [], "count": 0}
    except Exception as e:
        logger.warning("Judge scoring failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e), "judges": [], "count": 0}


@council_router.get("/api/judges/{netuid}")
async def api_judges_netuid(netuid: int):
    """Return detailed judge breakdown for one subnet."""
    return await asyncio.to_thread(_api_judges_netuid_sync, netuid)


def _api_judges_netuid_sync(netuid: int):
    try:
        subnets, _source = _get_subnets_for_scoring()
        if not subnets:
            return {"error": "subnet not found", "netuid": netuid}

        from internal.judges.subnet_judges import score_subnet

        target = next(
            (s for s in subnets if s.get("netuid") == netuid or s.get("id") == netuid),
            None,
        )
        if target:
            return score_subnet(netuid, target)
    except Exception as e:
        logger.warning("Judge netuid lookup failed for %s: %s", netuid, e)
    return {"error": "subnet not found", "netuid": netuid}


@council_router.get("/api/judges/{judge}/postmortems")
async def api_judge_postmortems(judge: str):
    """Return scientific-method postmortems for a single judge."""
    try:
        from internal.judges import get_judge
        from internal.judges.postmortems import list_for_judge

        name = judge.lower()
        if get_judge(name) is None:
            return {"status": "error", "error": f"Unknown judge: {judge}"}
        return {"status": "success", "judge": name, "postmortems": list_for_judge(name)}
    except Exception as exc:
        logger.warning("api_judge_postmortems failed: %s", exc)
        return {"status": "stub", "judge": judge, "postmortems": [], "error": str(exc)}


@council_router.get("/api/paper-portfolio")
async def api_paper_portfolio():
    """Return aggregate paper portfolios for all judges."""
    try:
        from internal.judges.portfolios import all_portfolios

        portfolios = all_portfolios()
    except Exception as e:
        logger.warning("Portfolio fetch failed: %s", e)
        portfolios = {}
    return {"aggregate": _aggregate_portfolios(portfolios), "judges": portfolios}


@council_router.get("/api/portfolios")
async def api_portfolios():
    """Return the current paper portfolios for Oracle, Echo and Pulse."""
    try:
        from internal.judges.portfolios import all_portfolios

        return {"status": "success", "portfolios": all_portfolios()}
    except Exception as exc:
        logger.warning("api_portfolios failed: %s", exc)
        return {"status": "stub", "portfolios": {}, "error": str(exc)}


@council_router.get("/api/postmortems")
async def api_postmortems(judge: Optional[str] = None):
    """Return all postmortems, optionally filtered by judge name."""
    try:
        from internal.judges.postmortems import all_postmortems, list_for_judge

        if judge:
            pms = list_for_judge(judge)
            return {"judge": judge, "postmortems": pms if isinstance(pms, list) else []}
        pms = all_postmortems()
        return {"postmortems": pms if isinstance(pms, dict) else {}}
    except Exception as e:
        logger.warning("Postmortem fetch failed: %s", e)
        return {"postmortems": {}}


@council_router.get("/api/postmortems/{judge_name}")
async def api_postmortems_by_judge(judge_name: str):
    """Return postmortems for a specific judge."""
    try:
        from internal.judges.postmortems import list_for_judge

        pms = list_for_judge(judge_name)
        return {"judge": judge_name, "postmortems": pms if isinstance(pms, list) else []}
    except Exception as e:
        logger.warning("Postmortem fetch failed for %s: %s", judge_name, e)
        return {"judge": judge_name, "postmortems": []}


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
