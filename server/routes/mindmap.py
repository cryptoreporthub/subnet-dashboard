"""Routes: mindmap."""
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

@router.get("/api/mindmap/summary")
def api_mindmap_summary_safe():
    simivision = _safe_simivision_payload()["data"]
    # Pull live Council expert weights and resolver stats so the mindmap stays
    # wired into the evidence -> signal -> decision -> learning cycle.
    engine = LearningEngine()
    stats = engine.get_stats()
    expert_weights = stats.get("expert_weights", {})
    resolved = resolver.get_resolved_predictions()
    scenario_summary = _safe_scenario_memory_summary()
    rotation_summary = _safe_rotation_summary()
    return {
        "status": "success",
        "data": {
            "acknowledgment": "Dashboard data ready",
            "noticed": ["Using safe cached subnet snapshot"],
            "opinion_changes": ["No significant opinion changes"],
            "technical_indicators": ["No strong technical signals"],
            "conviction": {
                "current": 50.0,
                "trend": "stable",
                "explanation": f"Derived from {simivision['meta']['count']} subnets",
            },
            "expert_insights": [
                {"expert": name.title(), "weight": weight}
                for name, weight in expert_weights.items()
            ],
            "expert_weights": expert_weights,
            "resolved_predictions": {
                "total": resolved.get("stats", {}).get("total", 0),
                "correct": resolved.get("stats", {}).get("correct", 0),
                "wrong": resolved.get("stats", {}).get("wrong", 0),
                "pending": resolved.get("stats", {}).get("pending", 0),
                "accuracy": resolved.get("stats", {}).get("accuracy", 0.0),
            },
            "scenario_memory": scenario_summary,
            "rotation_tracker": rotation_summary,
            "learning_status": {
                "enabled": True,
                "records": stats.get("total_records", 0),
                "last_updated": stats.get("last_updated") or simivision["meta"]["updated_at"],
            },
        },
    }



