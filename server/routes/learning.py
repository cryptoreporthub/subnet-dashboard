"""Routes: learning."""
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

@router.get("/api/learning/stats")
def api_learning_stats_safe():
    # Use the live learning engine so the dashboard exposes expert weights,
    # resolver stats, accuracy and a valid timestamp.
    engine = LearningEngine()
    stats = engine.get_stats()
    return {
        "status": "success",
        "data": {
            "expert_weights": stats.get("expert_weights", {}),
            "total_records": stats.get("total_records", 0),
            "accuracy": stats.get("accuracy", 0.0),
            "pending": stats.get("pending", 0),
            "resolved": stats.get("resolved", 0),
            "last_updated": stats.get("last_updated") or datetime.utcnow().isoformat() + "Z",
        },
    }



@router.post("/api/learning/trigger")
def api_learning_trigger():
    """Manually trigger a prediction-resolution cycle (the learning loop's judge).

    Runs the resolver immediately so pending predictions are graded and expert
    weights are nudged without waiting for the next scheduled tick (the
    scheduler runs every 15 minutes by default). Returns the cycle summary and
    the current scheduler state. Safe to call repeatedly.
    """
    scheduler = get_prediction_resolver_scheduler()
    if scheduler is None:
        # Scheduler not yet started (e.g. headless test): start it and run a
        # single synchronous cycle so the trigger is still effective.
        start_prediction_resolver_scheduler(immediate=False)
        scheduler = get_prediction_resolver_scheduler()

    cycle: Dict[str, Any] = {}
    if scheduler is not None:
        try:
            cycle = scheduler.run_once()
        except Exception as exc:
            cycle = {"ok": False, "error": str(exc)}

    return {
        "status": "success",
        "data": {
            "cycle": cycle,
            "scheduler": get_prediction_resolver_scheduler_state(),
            "triggered_at": datetime.utcnow().isoformat() + "Z",
        },
    }



@router.get("/api/scenario-memory")
async def api_scenario_memory():
    """Return the full regime-aware scenario memory snapshot."""
    try:
        _mark_fresh("scenario_memory")
        return {"status": "ok", **scenario_memory.get_memory_snapshot()}
    except Exception as e:
        logger.error("Error fetching scenario memory: %s", e)
        return {"status": "error", "scenarios": [], "regimes": {}, "stats": {}, "meta": {}, "error": str(e)}



@router.post("/api/scenario-memory")
async def api_scenario_memory_add(request: Request):
    """Record a new regime-aware scenario into persistent memory."""
    try:
        payload = await request.json()
    except Exception as e:
        return {"status": "error", "error": f"Invalid JSON body: {e}"}

    name = payload.get("name")
    features = payload.get("features", {})
    if not name or not isinstance(features, dict):
        return {"status": "error", "error": "Missing 'name' or 'features'"}

    try:
        scenario = scenario_memory.add_scenario(
            name=name,
            features=features,
            outcome=payload.get("outcome"),
            regime=payload.get("regime"),
            metadata=payload.get("metadata"),
        )
        return {"status": "ok", "scenario": scenario}
    except Exception as e:
        logger.error("Error adding scenario: %s", e)
        return {"status": "error", "error": str(e)}



@router.get("/api/learning-metrics")
async def api_learning_metrics():
    """Return learning-loop metrics: expert weights, accuracy, recent resolutions."""
    try:
        return _compute_learning_metrics()
    except Exception as e:
        logger.error("Error fetching learning metrics: %s", e)
        return {"error": str(e), "expert_weights": {}, "accuracy": 0.0}



