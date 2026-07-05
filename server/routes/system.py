"""Routes: system."""
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from datetime import datetime
import json, os, logging
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

@router.get("/health")
def health_check():
    return PlainTextResponse("OK")



@router.get("/api/health")
def api_health_check():
    """JSON health probe for Fly.io / monitoring tooling.

    Mirrors the plain-text ``/health`` route but returns a JSON body so probes
    that expect a structured response (and the ``/api/health`` path requested
    by external monitors) get a 200 instead of a 404.
    """
    return {"status": "ok"}



@router.get("/api/freshness")
def api_freshness():
    """Per-section "last updated" timestamps for the dashboard freshness badges.

    Returns ``{"last_updated": {section: iso_ts, ...}, "now": <iso>}``. The
    frontend polls this on load and every 30s to render "updated Xm ago"
    badges next to each section heading.
    """
    return _freshness_snapshot()



@router.get("/api/pick-history")
def api_pick_history():
    """Pick-of-the-Hour history + aggregate success metric.

    Returns the currently-tenured pick, the most recent finalized picks (each
    with absolute/median/percentile returns + success flag), and aggregate
    success stats (wins/losses/success_rate). A pick is "successful" when its
    absolute return beats the median subnet return over its tenure.
    """
    return _hour_pick_history(limit=20)



@router.get("/api/price-tracking/baselines")
def api_price_tracking_baselines():
    """Return the recorded baseline price history for all tracked subnets."""
    try:
        baseline_file = os.environ.get(
            "PRICE_BASELINE_FILE", "data/price_baselines.json"
        )
        if not os.path.exists(baseline_file):
            return {
                "status": "success",
                "meta": {"count": 0, "source": "file"},
                "baselines": [],
            }
        with open(baseline_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            data = []
        netuids = {e.get("netuid") for e in data if e.get("netuid") is not None}
        return {
            "status": "success",
            "meta": {
                "count": len(data),
                "tracked_subnets": len(netuids),
                "source": "file",
            },
            "baselines": data,
        }
    except Exception as exc:
        logger.warning("price-tracking/baselines failed: %s", exc)
        return {"status": "error", "error": str(exc), "baselines": []}



@router.get("/api/price-tracking/outcomes")
def api_price_tracking_outcomes():
    """Return recorded price outcomes (for debugging/verification)."""
    try:
        if not _MESSAGE_INTEL_AVAILABLE:
            return {"status": "success", "meta": {"count": 0}, "outcomes": []}
        db = _get_message_intel_db()
        if db is None:
            return {"status": "success", "meta": {"count": 0}, "outcomes": []}
        outcomes = db.list_price_outcomes(limit=100)
        return {
            "status": "success",
            "meta": {"count": len(outcomes)},
            "outcomes": outcomes,
        }
    except Exception as exc:
        logger.warning("price-tracking/outcomes failed: %s", exc)
        return {"status": "error", "error": str(exc), "outcomes": []}



@router.get("/api/resolve-predictions")
def api_resolve_predictions():
    """Trigger prediction resolution for any due predictions."""
    try:
        subnets, _ = _get_subnets_with_source()
        result = resolver.resolve_due_predictions(subnets)
        return {"status": "success", "data": result}
    except Exception as exc:
        logger.warning("resolve_due_predictions failed: %s", exc)
        return {
            "status": "stub",
            "data": {"resolved_now": [], "resolved": [], "pending": [], "stats": {}},
            "error": str(exc),
        }



