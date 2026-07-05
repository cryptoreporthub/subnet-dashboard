"""Routes: indicators."""
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

@router.get("/api/indicators/scheduler")
def api_indicators_scheduler():
    """Return the current state of the background indicator scheduler."""
    return {
        "status": "success",
        "data": get_indicator_scheduler_state(),
    }



@router.get("/api/indicators-convergence")
async def api_indicators_convergence():
    """Return multi-indicator oversold/overbought convergence for top subnets."""
    try:
        subnets, _ = _get_subnets_with_source()
        ranked = sorted(subnets, key=lambda s: (s.get("emission", 0), s.get("apy", 0), s.get("volume", 0)), reverse=True)
        rows = []
        for sn in ranked[:6]:
            indicators = _compute_technical_indicators(sn)
            rows.append({
                "netuid": sn.get("netuid"),
                "name": sn.get("name"),
                "oversold": _detect_oversold_convergence(indicators),
                "overbought": _detect_overbought_convergence(indicators),
            })
        _mark_fresh("indicators")
        return {"subnets": rows}
    except Exception as e:
        logger.error("Error fetching indicators convergence: %s", e)
        return {"subnets": [], "error": str(e)}



@router.get("/api/indicators")
async def api_indicators():
    """Return the latest technical-indicator state from the indicator engine."""
    try:
        return {
            "status": "success",
            "data": IndicatorEngine().get_indicator_state(),
        }
    except Exception as e:
        logger.error("Error fetching indicator state: %s", e)
        return {"status": "error", "data": {}, "error": str(e)}



