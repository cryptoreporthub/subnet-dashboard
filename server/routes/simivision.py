"""Routes: simivision."""
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

@router.get("/api/top-pick/day")
def api_top_pick_day():
    """Return the top pick for the current day with a safe fallback."""
    subnets, _ = _get_subnets_with_source()
    # Use the same real market-wide mood proxy as the homepage so the day
    # pick endpoint stays in sync with the rendered dashboard.
    market_context = {"tao_change_24h": _market_mood_proxy(subnets)}
    try:
        _dp_raw = get_or_create_today_pick(subnets, market_context)
        day_pick = _dp_raw.get("pick") if isinstance(_dp_raw, dict) and _dp_raw.get("pick") else _dp_raw
    except Exception as exc:
        logger.error("Error selecting daily pick: %s", exc)
        day_pick = None
    if not day_pick:
        return {"picks": [_highest_emission_pick(subnets)]}
    _mark_fresh("top_pick_day")
    # Record the day pick's market context into the scenario memory so
    # /api/scenario-memory reflects real picks, not just resolved predictions.
    try:
        candidate = day_pick.get("subnet") if isinstance(day_pick, dict) else None
        if isinstance(candidate, dict):
            sn = next((s for s in subnets if s.get("netuid") == candidate.get("netuid")), {})
            _record_pick_scenario({
                "name": candidate.get("name"),
                "netuid": candidate.get("netuid"),
                "score": day_pick.get("score", 0.0),
                "confidence": day_pick.get("confidence", 0.0),
                "scenario_tags": day_pick.get("scenario_tags", {}),
                "signals": {
                    "price_change_24h": sn.get("price_change_24h"),
                    "price_change_7d": sn.get("price_change_7d"),
                    "emission": sn.get("emission"),
                    "apy": sn.get("apy"),
                    "volume": sn.get("volume"),
                },
            }, market_context)
    except Exception as exc:
        logger.warning("day pick scenario record failed: %s", exc)
    return {"picks": [day_pick]}



@router.get("/api/simivision")
def api_simivision_safe():
    return _safe_simivision_payload()



@router.post("/api/simivision/chat")
async def api_simivision_chat(request: Request):
    """LLM chat endpoint for SimiVision powered by Chutes AI.

    Accepts a JSON body with a ``message`` field, builds a live-subnet prompt
    from SimiVision context, and calls the Chutes API (``deepseek-ai/DeepSeek-V3.2-TEE``).
    Falls back gracefully when Chutes is unreachable.

    Returns ``{"reply": "...", "model": "chutes/deepseek-v3.2-tee"}`` on success
    or an error shape on failure.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    message = (payload or {}).get("message", "") or ""

    if not message.strip():
        return {"reply": "Please provide a question in the `message` field.", "model": ""}

    try:
        # 1. Fetch subnet data
        subnets, source = _get_subnets_with_source()
        simivision = _safe_simivision_payload()["data"]

        # 2. Load soul_map.json for learning context
        engine = LearningEngine()
        soul_map = engine.load_soul_map()
        stats = engine.get_stats()
        expert_weights = stats.get("expert_weights", {})

        # 3. Load predictions and daily picks for enriched context
        predictions = _safe_load_json("data", "predictions.json", default={}).get("predictions", [])
        daily_pick_data = _safe_load_json("data", "daily_picks.json", default=[{}])
        daily_pick = daily_pick_data[0] if daily_pick_data else {}

        # 4. Build prompt with context
        top = simivision.get("top", [])
        context = {
            "source": source,
            "simivision_picks": top,
            "market_overview": {
                "count": simivision.get("meta", {}).get("count", len(subnets)),
                "updated_at": simivision.get("meta", {}).get("updated_at"),
            },
            "expert_weights": expert_weights,
            "soul_map": soul_map,
            "predictions": predictions,
            "daily_pick": daily_pick,
        }
        prompt = _build_simivision_prompt(message, context)

        # 5. Call LLM API (with graceful local fallback)
        reply, llm_used = _call_llm(prompt, message, context)

        model_tag = os.environ.get("CHUTES_MODEL", "deepseek-ai/DeepSeek-V3.2-TEE")
        display_model = f"chutes/{model_tag.split('/')[-1].lower()}" if llm_used else "local-fallback"

        return {"reply": reply, "model": display_model}

    except Exception as exc:
        logger.error("SimiVision chat failed: %s", exc, exc_info=True)
        return {
            "reply": "SimiVision is temporarily unavailable. The Chutes AI service may be unreachable. Please try again shortly.",
            "model": "",
        }



@router.get("/api/top-picks")
async def api_top_picks():
    """Return top 3 subnets by short-horizon and 24h Council state-vector scores."""
    try:
        subnets, _ = _get_subnets_with_source()
        # Use the same real market-wide mood proxy as the homepage so the
        # short-horizon / day scores here match the audited picks everywhere.
        market_context = {"tao_change_24h": _market_mood_proxy(subnets)}

        hour_scored = []
        day_scored = []
        for sn in subnets:
            hour = score_subnet_for_hour(sn, market_context)
            day = score_subnet_for_day(sn, market_context)
            hour_scored.append({"subnet": sn, "score": hour})
            day_scored.append({"subnet": sn, "score": day})

        hour_scored.sort(key=lambda x: x["score"]["total_score"], reverse=True)
        day_scored.sort(key=lambda x: x["score"]["total_score"], reverse=True)

        def _format(item):
            sn = item["subnet"]
            sc = item["score"]
            return {
                "netuid": sn.get("netuid"),
                "name": sn.get("name"),
                "symbol": sn.get("symbol"),
                "score": sc["total_score"],
                "confidence": sc["confidence"],
                "expert_contributions": sc["expert_contributions"],
                "signals": {
                    "price_change_24h": sn.get("price_change_24h"),
                    "price_change_7d": sn.get("price_change_7d"),
                    "emission": sn.get("emission"),
                    "apy": sn.get("apy"),
                    "volume": sn.get("volume"),
                },
                "scenario_tags": sc["scenario_tags"],
            }

        return {
            "hour_picks": [_format(i) for i in hour_scored[:3]],
            "day_picks": [_format(i) for i in day_scored[:3]],
        }
    except Exception as e:
        logger.error("Error fetching top picks: %s", e)
        return {"hour_picks": [], "day_picks": [], "error": str(e)}



@router.get("/api/top-pick/hour")
async def api_top_pick_hour():
    """Return the top short-horizon picks with a safe fallback.

    Uses the shared ``_ordered_hour_picks`` helper so the #1 pick is identical
    to what the homepage renders (RedTeam-audited hourly pick first, then raw
    score-ranked fill). This guarantees the API and homepage never diverge.
    """
    try:
        subnets, _ = _get_subnets_with_source()
        # Use the SAME real market-wide mood proxy as the homepage so the
        # audited #1 pick is byte-for-byte identical between the API and the
        # rendered dashboard (a static 0.0 here previously let the two drift).
        market_context = {"tao_change_24h": _market_mood_proxy(subnets)}
        picks = _ordered_hour_picks(subnets, market_context, limit=3)
        _mark_fresh("top_pick_hour")
        if picks:
            return {"picks": picks}
        return {"picks": [_highest_emission_pick(subnets)]}
    except Exception as e:
        logger.error("Error fetching hour pick: %s", e)
        subnets, _ = _get_subnets_with_source()
        return {"picks": [_highest_emission_pick(subnets)]}



