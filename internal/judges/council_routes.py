"""
FastAPI APIRouter for the Judge Council endpoints.

Provides:
  GET /api/judges                    - Score all subnets through the three-judge council
  GET /api/judges/{netuid}           - Judge breakdown for one subnet
  GET /api/judges/{judge}/postmortems - Postmortems for a single judge
  GET /api/council                   - Full merged data pipeline (Blockmachine + TaoStats + TMC + judges)
  GET /api/paper-portfolio           - Aggregate paper portfolio across all judges
  GET /api/portfolios                - Per-judge paper portfolios
  GET /api/postmortems               - Postmortems for all judges
  GET /api/postmortems/{judge_name}  - Postmortems for a single judge
  GET /judge-council                 - Standalone Judge Council HTML page
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

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


def _aggregate_portfolios(portfolios: Dict[str, Any]) -> Dict[str, Any]:
    """Roll up per-judge paper portfolios into a single summary."""
    total_open = 0
    total_closed = 0
    total_pnl = 0.0
    total_wins = 0
    total_losses = 0
    for pf in portfolios.values():
        if not isinstance(pf, dict):
            continue
        summary = pf.get("summary", {})
        total_open += summary.get("open_positions", len(pf.get("open_positions", [])))
        total_closed += summary.get("total_closed", len(pf.get("closed_positions", [])))
        total_pnl += float(summary.get("total_pnl_pct", 0) or 0)
        total_wins += int(summary.get("win_count", 0) or 0)
        total_losses += int(summary.get("loss_count", 0) or 0)
    total_trades = total_wins + total_losses
    return {
        "open_positions": total_open,
        "closed_positions": total_closed,
        "total_pnl": round(total_pnl, 4),
        "win_rate": round(total_wins / total_trades, 4) if total_trades > 0 else 0.0,
        "total_trades": total_trades,
    }


def _lookup_subnet(netuid: int) -> Optional[Dict[str, Any]]:
    """Find subnet metadata from live TMC data or the committed registry."""
    try:
        from fetchers.taomarketcap import get_all_subnets

        for subnet in get_all_subnets() or []:
            candidate = int(subnet.get("netuid", subnet.get("id", -1)))
            if candidate == netuid:
                return dict(subnet)
    except Exception as exc:
        logger.warning("Subnet lookup via TMC failed: %s", exc)

    try:
        with open("config/registry.json", "r", encoding="utf-8") as handle:
            registry = json.load(handle)
        for entry in registry.values():
            candidate = int(entry.get("id", entry.get("netuid", -1)))
            if candidate == netuid:
                subnet = dict(entry)
                subnet.setdefault("netuid", netuid)
                return subnet
    except Exception as exc:
        logger.warning("Subnet lookup via registry failed: %s", exc)
    return None


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
        from fetchers.taomarketcap import get_all_subnets
        from internal.judges.subnet_judges import score_all_subnets

        subnets_data = get_all_subnets()
        subnets_data = _deduplicate_subnets(subnets_data or [])
        if not subnets_data:
            try:
                with open("config/registry.json", "r", encoding="utf-8") as handle:
                    registry = json.load(handle)
                subnets_data = [dict(entry) for entry in registry.values()]
                subnets_data = _deduplicate_subnets(subnets_data)
                source = "registry"
            except Exception:
                source = "none"
        else:
            source = "taomarketcap"

        if not subnets_data:
            return {"success": False, "error": "No subnet data available", "judges": [], "count": 0}

        result = score_all_subnets(subnets_data)
        result = _deduplicate_subnets(result)
        logger.info("Judges: scored %d unique subnets (source=%s)", len(result), source)
        return {"success": True, "judges": result, "count": len(result), "source": source}
    except Exception as e:
        logger.warning("Judge scoring failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e), "judges": [], "count": 0}


@council_router.get("/api/judges/{netuid}")
async def api_judges_netuid(netuid: int):
    """Return detailed judge breakdown for one subnet."""
    try:
        from internal.judges.subnet_judges import score_subnet

        subnet = _lookup_subnet(netuid)
        if subnet is None:
            return {"error": "subnet not found", "netuid": netuid}
        return score_subnet(netuid, subnet)
    except Exception as exc:
        logger.warning("Single-subnet judge scoring failed: %s", exc)
        return {"error": str(exc), "netuid": netuid}


@council_router.get("/api/paper-portfolio")
async def api_paper_portfolio():
    """Return aggregate paper portfolio across all judges."""
    try:
        from internal.judges.portfolios import all_portfolios

        portfolios = all_portfolios()
        return {
            "success": True,
            "aggregate": _aggregate_portfolios(portfolios),
            "judges": portfolios,
        }
    except Exception as e:
        logger.warning("Portfolio fetch failed: %s", e)
        return {
            "success": False,
            "error": str(e),
            "aggregate": _aggregate_portfolios({}),
            "judges": {},
        }


@council_router.get("/api/portfolios")
async def api_portfolios():
    """Return the current paper portfolios for Oracle, Echo, and Pulse."""
    try:
        from internal.judges.portfolios import all_portfolios

        return {"status": "success", "portfolios": all_portfolios()}
    except Exception as exc:
        logger.warning("api_portfolios failed: %s", exc)
        return {"status": "stub", "portfolios": {}, "error": str(exc)}


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


@council_router.get("/api/postmortems/{judge_name}")
async def api_postmortems_by_judge(judge_name: str):
    """Return postmortems for a specific judge."""
    try:
        from internal.judges.judges import get_judge
        from internal.judges.postmortems import list_for_judge

        name = judge_name.lower()
        if get_judge(name) is None:
            return {
                "status": "error",
                "error": f"Unknown judge: {judge_name}",
                "judge": name,
                "postmortems": [],
            }
        return {"status": "success", "judge": name, "postmortems": list_for_judge(name)}
    except Exception as exc:
        logger.warning("api_postmortems_by_judge failed: %s", exc)
        return {"status": "stub", "judge": judge_name, "postmortems": [], "error": str(exc)}


@council_router.get("/api/judges/{judge}/postmortems")
async def api_judge_postmortems(judge: str):
    """Return scientific-method postmortems for a single judge."""
    try:
        from internal.judges.judges import get_judge
        from internal.judges.postmortems import list_for_judge

        name = judge.lower()
        if get_judge(name) is None:
            return {"status": "error", "error": f"Unknown judge: {judge}", "postmortems": []}
        return {"status": "success", "judge": name, "postmortems": list_for_judge(name)}
    except Exception as exc:
        logger.warning("api_judge_postmortems failed: %s", exc)
        return {"status": "stub", "judge": judge, "postmortems": [], "error": str(exc)}


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
