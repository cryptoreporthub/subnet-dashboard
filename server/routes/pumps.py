"""Routes: pumps."""
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

@router.get("/api/pump-analytics")
async def api_pump_analytics(netuid: Optional[int] = None):
    """Return pump cycle analytics for all subnets or a specific one.

    Optional ``?netuid=`` filter restricts the response to a single subnet.
    """
    if not _PUMP_TRACKER_AVAILABLE:
        return {
            "status": "error",
            "data": {
                "subnets": [],
                "meta": {
                    "tracked_subnets": 0,
                    "total_cycles": 0,
                    "avg_proneness": 0.0,
                    "top_pump_candidates": [],
                    "updated_at": None,
                },
            },
        }
    tracker = get_pump_tracker()
    if tracker is None:
        return {
            "status": "error",
            "data": {
                "subnets": [],
                "meta": {
                    "tracked_subnets": 0,
                    "total_cycles": 0,
                    "avg_proneness": 0.0,
                    "top_pump_candidates": [],
                    "updated_at": None,
                },
            },
        }
    data = tracker.get_all_analytics()
    if netuid is not None:
        data["data"]["subnets"] = [s for s in data["data"]["subnets"] if s.get("netuid") == netuid]
        data["data"]["meta"]["tracked_subnets"] = len(data["data"]["subnets"])
    return data



