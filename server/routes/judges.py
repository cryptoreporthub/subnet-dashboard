"""Routes: judges."""
from fastapi import APIRouter, Request
import json
import logging
import math
import os
import sys
import threading
import time
import traceback
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fetchers.taomarketcap import get_all_subnets, get_subnet_data
    from internal.council.state_vector import (
    from internal.council.daily_pick import select_daily_pick
    from internal.council.daily_pick_engine import get_or_create_today_pick
    from internal.council.hourly_pick import select_hourly_pick
    from internal.council import pick_history
    from internal import freshness_tracker
    from internal.council import resolver, scenario_memory, rotation_tracker
    from internal.judges import all_judges, get_judge, on_prediction_created, on_prediction_resolved
    from internal.judges.portfolios import all_portfolios
    from internal.judges.postmortems import all_postmortems, list_for_judge
    from internal.judges.subnet_judges import score_all_subnets, score_subnet
    from internal.council.weights import load_weights, save_weights
    from internal.indicators import (
    from internal.council.resolver_scheduler import (
    from datastore.learning_engine import LearningEngine
    from internal.pump_tracker import (
    from message_intel import Database as _MessageIntelDatabase
    from message_intel import NLPAnalyzer as _MessageIntelNLPAnalyzer
    from message_intel import JuryBridge as _MessageIntelJuryBridge
    from message_intel import PriceTracker as _MessageIntelPriceTracker
    from message_intel import SelfLearning as _MessageIntelSelfLearning
                import shutil
        from message_intel.telegram_listener import TelegramListener  # lazy import
            import requests
        from internal.llm.explainer import generate_ai_response

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/api/council/weights")
def api_council_weights():
    """Return the current Council expert weights."""
    try:
        return {"status": "success", "data": load_weights()}
    except Exception as exc:
        logger.warning("load_weights failed: %s", exc)
        return {
            "status": "stub",
            "data": {"quant": 1.0, "hype": 1.0, "contrarian": 1.0, "technical": 1.0},
            "error": str(exc),
        }



@router.get("/api/judges")
async def api_judges():
    """Return all subnet judge scores sorted by consensus."""
    with _JUDGE_SCORES_LOCK:
        scores = list(_JUDGE_SCORES)
    return {
        "judges": scores,
        "meta": {
            "count": len(scores),
            "refreshed_at": _JUDGE_SCORES_REFRESHED,
            "degraded_sources": [],
        },
    }



@router.get("/api/judges/{netuid}")
async def api_judges_netuid(netuid: int):
    """Return detailed judge breakdown for one subnet."""
    with _JUDGE_SCORES_LOCK:
        for entry in _JUDGE_SCORES:
            if entry["netuid"] == netuid:
                return entry
    # If not cached, compute live
    try:
        subnets_data = get_all_subnets()
        subnets = subnets_data if isinstance(subnets_data, list) else subnets_data.get("subnets", [])
        target = next((s for s in subnets if s.get("netuid") == netuid or s.get("id") == netuid), None)
        if target:
            return score_subnet(netuid, target)
    except Exception:
        pass
    return {"error": "subnet not found", "netuid": netuid}



@router.get("/api/paper-portfolio")
async def api_paper_portfolio():
    """Return aggregate paper portfolios for all judges."""
    try:
        portfolios = all_portfolios()
    except Exception:
        portfolios = {}
    return {"aggregate": _aggregate_portfolios(portfolios), "judges": portfolios}



@router.get("/api/postmortems")
async def api_postmortems(judge: Optional[str] = None):
    """Return all postmortems, optionally filtered by judge name."""
    try:
        if judge:
            pms = list_for_judge(judge)
            return {"judge": judge, "postmortems": pms if isinstance(pms, list) else []}
        pms = all_postmortems()
        return {"postmortems": pms if isinstance(pms, dict) else {}}
    except Exception:
        return {"postmortems": {}}



@router.get("/api/postmortems/{judge_name}")
async def api_postmortems_by_judge(judge_name: str):
    """Return postmortems for a specific judge (alternative path)."""
    try:
        pms = list_for_judge(judge_name)
        return {"judge": judge_name, "postmortems": pms if isinstance(pms, list) else []}
    except Exception:
        return {"judge": judge_name, "postmortems": []}



@router.get("/api/portfolios")
def api_portfolios():
    """Return the current paper portfolios for Oracle, Echo and Pulse."""
    try:
        return {"status": "success", "portfolios": all_portfolios()}
    except Exception as exc:
        logger.warning("api_portfolios failed: %s", exc)
        return {"status": "stub", "portfolios": {}, "error": str(exc)}



@router.get("/api/judges/{judge}/postmortems")
def api_judge_postmortems(judge: str):
    """Return scientific-method postmortems for a single judge."""
    try:
        name = judge.lower()
        if get_judge(name) is None:
            return {"status": "error", "error": f"Unknown judge: {judge}"}
        return {"status": "success", "judge": name, "postmortems": list_for_judge(name)}
    except Exception as exc:
        logger.warning("api_judge_postmortems failed: %s", exc)
        return {"status": "stub", "judge": judge, "postmortems": [], "error": str(exc)}



@router.get("/api/oracle")
def api_oracle():
    """Return a minimal oracle snapshot from live subnet data."""
    try:
        subnets, source = _get_subnets_with_source()
        snapshot = [
            {
                "netuid": s.get("netuid"),
                "name": s.get("name"),
                "symbol": s.get("symbol"),
                "price": s.get("price"),
                "price_change_24h": s.get("price_change_24h"),
            }
            for s in subnets[:10]
        ]
        return {"status": "success", "source": source, "data": snapshot}
    except Exception as exc:
        logger.warning("oracle snapshot failed: %s", exc)
        return {"status": "stub", "source": "error", "data": [], "error": str(exc)}



