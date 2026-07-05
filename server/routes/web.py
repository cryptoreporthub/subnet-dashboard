"""Routes: web."""
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

@router.post("/api/message-intel/ingest")
async def api_message_intel_ingest(request: Request):
    """Ingest a Telegram message, run NLP + jury, and persist the verdict."""
    if not _MESSAGE_INTEL_AVAILABLE:
        return {"status": "error", "error": "Message intelligence package unavailable"}

    try:
        payload = await request.json()
    except Exception as e:
        return {"status": "error", "error": f"Invalid JSON body: {e}"}

    if not isinstance(payload, dict) or not payload.get("content"):
        return {"status": "error", "error": "Missing required field: content"}

    try:
        db = _get_message_intel_db()
        nlp = _get_message_intel_nlp()
        jury = _get_message_intel_jury()
        price_tracker = _get_message_intel_price_tracker()

        message_id = db.save_message(payload)
        analysis = nlp.analyze(payload.get("content", ""))
        db.save_analysis(message_id, analysis)
        verdict = jury.evaluate(message_id, payload.get("content", ""), analysis)
        db.save_verdict(message_id, verdict)
        price_tracker.snapshot(message_id)

        return {
            "status": "success",
            "message_id": message_id,
            "analysis": analysis,
            "verdict": verdict,
        }
    except Exception as e:
        logger.error("Error ingesting message intel: %s", e)
        return {"status": "error", "error": str(e)}



@router.get("/api/message-intel/list")
async def api_message_intel_list(limit: int = 50, offset: int = 0):
    """List ingested messages with verdicts and analysis."""
    if not _MESSAGE_INTEL_AVAILABLE:
        return {"status": "error", "messages": [], "error": "Message intelligence package unavailable"}

    try:
        db = _get_message_intel_db()
        messages = db.list_messages(limit=limit, offset=offset)
        return {
            "status": "success",
            "count": len(messages),
            "messages": messages,
        }
    except Exception as e:
        logger.error("Error listing message intel: %s", e)
        return {"status": "error", "messages": [], "error": str(e)}



@router.get("/api/message-intel/detail/{msg_id}")
async def api_message_intel_detail(msg_id: int):
    """Return full details for a single message including metrics and verdict."""
    if not _MESSAGE_INTEL_AVAILABLE:
        return {"status": "error", "error": "Message intelligence package unavailable"}

    try:
        db = _get_message_intel_db()
        message = db.get_message(msg_id)
        if message is None:
            return {"status": "error", "error": "Message not found"}
        return {"status": "success", "message": message}
    except Exception as e:
        logger.error("Error fetching message intel detail: %s", e)
        return {"status": "error", "error": str(e)}



@router.get("/api/message-intel/chatter")
async def api_message_intel_chatter(min_conviction: float = 0.6, limit: int = 50):
    """Return high-conviction messages (the 'chatter' feed)."""
    if not _MESSAGE_INTEL_AVAILABLE:
        return {"status": "error", "messages": [], "error": "Message intelligence package unavailable"}

    try:
        db = _get_message_intel_db()
        messages = db.list_high_conviction_messages(min_conviction=min_conviction)
        return {
            "status": "success",
            "count": len(messages[:limit]),
            "messages": messages[:limit],
        }
    except Exception as e:
        logger.error("Error fetching message intel chatter: %s", e)
        return {"status": "error", "messages": [], "error": str(e)}



@router.get("/api/message-intel/patterns")
async def api_message_intel_patterns(limit: int = 20):
    """Return discovered pattern correlations from the learning loop."""
    if not _MESSAGE_INTEL_AVAILABLE:
        return {"status": "error", "patterns": [], "error": "Message intelligence package unavailable"}

    try:
        db = _get_message_intel_db()
        patterns = db.list_patterns(limit=limit)
        return {
            "status": "success",
            "count": len(patterns),
            "patterns": patterns,
        }
    except Exception as e:
        logger.error("Error fetching message intel patterns: %s", e)
        return {"status": "error", "patterns": [], "error": str(e)}



@router.get("/api/predictions/resolver")
def api_predictions_resolver_state():
    """Return the current state of the background prediction resolver.

    Exposes whether the resolver is running, when it last graded predictions,
    and how many it has resolved/expired so the learning loop's health is
    observable from the dashboard.
    """
    return {
        "status": "success",
        "data": get_prediction_resolver_scheduler_state(),
    }



@router.post("/api/predictions/resolver/run")
def api_predictions_resolver_run():
    """Trigger a single prediction-resolution cycle on demand.

    Useful for clearing a backlog of stuck ``pending`` predictions without
    waiting for the next scheduled tick. Returns the cycle summary.
    """
    scheduler = get_prediction_resolver_scheduler()
    if scheduler is None:
        return {
            "status": "error",
            "message": "prediction resolver scheduler is not initialized",
        }, 500
    try:
        result = scheduler.run_once()
        return {"status": "success", "data": result}
    except Exception as exc:
        logger.warning("Manual prediction resolver run failed: %s", exc)
        return {"status": "error", "message": str(exc)}, 500



@router.get("/")
async def dashboard(request: Request):
    """Render the SimiVision dashboard server-side via Jinja2.

    Context flows: server fetches subnets + SimiVision picks + mindmap summary
    + learning stats -> renders into templates/index.html -> user sees the
    complete dashboard. Vanilla JS polls /api/subnets every 5 min for refresh.

    The route is hardened so that any partial failure still yields a renderable
    context: every template key is guaranteed, and per-section helpers fall back
    to safe defaults rather than aborting the whole page.
    """
    subnets: List[Dict[str, Any]] = []
    source = "unknown"
    premium = _default_premium_context()
    # Derive a real market-wide mood from the average subnet 24h change so the
    # "Market Mood" scenario tag reflects actual movement instead of a static
    # 0.0 (which always classified as "neutral"). Recomputed after subnets load.
    market_context = {"tao_change_24h": 0.0}
    hour_picks: List[Dict[str, Any]] = []
    day_picks: List[Dict[str, Any]] = []
    daily_pick: Dict[str, Any] = {}
    rotation_tracker: Dict[str, Any] = _default_rotation_tracker()
    scenario_memory_snapshot: Dict[str, Any] = _default_scenario_memory()
    indicators_convergence: Dict[str, Any] = {"subnets": []}
    render_error: Optional[str] = None

    try:
        subnets, source = _get_subnets_with_source()
        _mark_fresh("subnets")
    except Exception as e:
        logger.error("Error fetching subnets for dashboard: %s", e)
        subnets, source = [], "error"

    # Recompute the market mood now that we have real subnets.
    market_context = {"tao_change_24h": _market_mood_proxy(subnets)}

    try:
        premium = _build_premium_context(subnets)
        # The premium context composes simivision picks, technical indicators,
        # predictions, social sentiment, and judge cards in one pass.
        _mark_fresh("simivision_picks")
        _mark_fresh("indicators")
        _mark_fresh("predictions")
        _mark_fresh("social_sentiment")
        _mark_fresh("judges")
    except Exception as e:
        logger.error("Error building premium context: %s", e)
        premium = _default_premium_context()

    try:
        # Use the SAME shared helper as /api/top-pick/hour so the homepage #1
        # pick always matches the highest-scored (audited) pick from the API.
        # The helper returns a unified shape carrying both top-level
        # name/netuid/score/confidence/signals/scenario_tags (template) and
        # nested subnet{}/action (API), and records each pick into the
        # regime-aware scenario memory.
        hour_picks = _ordered_hour_picks(subnets, market_context, limit=3)
        _mark_fresh("top_pick_hour")
    except Exception as e:
        logger.error("Error computing hour picks: %s", e)
        hour_picks = []

    try:
        _dp_raw = get_or_create_today_pick(subnets, market_context)
        daily_pick_result = _dp_raw.get("pick") if isinstance(_dp_raw, dict) and _dp_raw.get("pick") else _dp_raw
        if daily_pick_result and daily_pick_result.get("subnet"):
            candidate = daily_pick_result["subnet"]
            sn = next(
                (s for s in subnets if s.get("netuid") == candidate.get("netuid")),
                {},
            )
            _day_pick = {
                "netuid": candidate.get("netuid"),
                "name": candidate.get("name"),
                "symbol": candidate.get("symbol"),
                "score": daily_pick_result.get("score", 0.0),
                "confidence": daily_pick_result.get("confidence", 0.0),
                "signals": {
                    "price_change_24h": sn.get("price_change_24h"),
                    "price_change_7d": sn.get("price_change_7d"),
                    "emission": sn.get("emission"),
                    "apy": sn.get("apy"),
                    "volume": sn.get("volume"),
                },
                "scenario_tags": daily_pick_result.get("scenario_tags", {}),
            }
            day_picks.append(_day_pick)
            # Record the day pick's market context into the scenario memory.
            _record_pick_scenario(_day_pick, market_context)
            _mark_fresh("top_pick_day")
    except Exception as e:
        logger.error("Error computing day picks: %s", e)
        day_picks = []

    # Live Council State Vector fallback: never render an empty council. If the
    # backend computation returned no picks but subnets exist, fall back to the
    # highest-ranked subnet so the homepage always shows a state vector.
    if not hour_picks and subnets:
        hour_picks = [_fallback_state_pick(subnets)]
    if not day_picks and subnets:
        day_picks = [_fallback_state_pick(subnets)]

    try:
        # Use the Council engine directly so the homepage shows the audited,
        # persisted daily pick. ``get_or_create_today_pick`` returns the engine
        # payload whose ``pick`` key holds the actual pick data
        # (subnet/action/final_confidence/confidence/audit/scenario_tags) that
        # templates/index.html renders as ``daily_pick.*``.
        daily_pick_result = get_or_create_today_pick(subnets, market_context)
        daily_pick = daily_pick_result.get("pick") if isinstance(daily_pick_result, dict) else None
        if not isinstance(daily_pick, dict):
            daily_pick = {}
    except Exception as e:
        logger.error("Error fetching daily pick: %s", e)
        daily_pick = {}

    try:
        rotation_tracker = await api_rotation_tracker()
        _mark_fresh("rotation")
    except Exception as e:
        logger.error("Error fetching rotation tracker: %s", e)
        rotation_tracker = _default_rotation_tracker()

    try:
        scenario_memory_snapshot = await api_scenario_memory()
        _mark_fresh("scenario_memory")
    except Exception as e:
        logger.error("Error fetching scenario memory: %s", e)
        scenario_memory_snapshot = _default_scenario_memory()

    # Enrich each pick with the latest recorded scenario for its subnet
    # (regime, features, outcome) and let the recorded regime override the live
    # "Market Mood" tag when available. Falls back to the live indicator-derived
    # tags (already computed above) when no scenario has been recorded yet.
    scenarios_by_name = _latest_scenario_by_name(
        scenario_memory_snapshot.get("scenarios", [])
    )
    for pick in hour_picks:
        _enrich_pick_scenario(pick, scenarios_by_name)
    for pick in day_picks:
        _enrich_pick_scenario(pick, scenarios_by_name)

    # Fallback: if the picks pipeline produced nothing (e.g. scoring failed but
    # subnets are available), pull the top subnets by conviction and build
    # minimal pick objects carrying their current indicator-derived scenario
    # tags so the sections never render empty or all-defaults.
    if not hour_picks and subnets:
        hour_picks = _build_fallback_picks(subnets, market_context, "hour")
    if not day_picks and subnets:
        day_picks = _build_fallback_picks(subnets, market_context, "day")

    try:
        indicators_convergence = await api_indicators_convergence()
    except Exception as e:
        logger.error("Error fetching indicators convergence: %s", e)
        indicators_convergence = {"subnets": []}

    context = {
        "subnets": subnets,
        "data_source": source,
        "mindmap": get_mindmap_summary(),
        "learning_stats": get_learning_stats(),
        "simivision": get_simivision_data(),
        "rotation_tokens": _ROTATION_TOKENS,
        "simivision_picks": premium.get("simivision_picks", []),
        "undervalued_radar": premium.get("undervalued_radar", []),
        "technical_indicators": premium.get("technical_indicators", []),
        "market_intelligence": premium.get("market_intelligence", _default_market_intelligence()),
        "staking_analytics": premium.get("staking_analytics", {
            "total_stake": 0.0,
            "avg_apy": 0.0,
            "subnet_count": 0,
            "top_yield": [],
        }),
        "council_weights": premium.get("council_weights", []),
        "expert_weights": premium.get("expert_weights", {}),
        "mindmap_trail": premium.get("mindmap_trail", []),
        "signal_impact": premium.get("signal_impact", []),
        "patterns": premium.get("patterns", []),
        "predictions": premium.get("predictions", []),
        "learning_metrics": premium.get("learning_metrics", _default_learning_metrics()),
        "social_sentiment": premium.get("social_sentiment", []),
        "indicators_convergence": premium.get("indicators_convergence", {"oversold": {}, "overbought": {}}),
        "momentum_charts": premium.get("momentum_charts", {"treemap": [], "radar": {"labels": [], "datasets": []}}),
        "judge_cards": premium.get("judge_cards", []),
        "usd_rate": premium.get("usd_rate"),
        "hour_picks": hour_picks,
        "day_picks": day_picks,
        "daily_pick": daily_pick,
        "rotation_tracker": rotation_tracker,
        "scenario_memory": scenario_memory_snapshot,
        "api_indicators_convergence": indicators_convergence,
        "pump_analytics": _safe_pump_analytics(),
    }

    try:
        context["request"] = request
        return templates.TemplateResponse("index.html", context)
    except Exception as e:
        logger.error("Error rendering dashboard template: %s\n%s", e, traceback.format_exc())
        render_error = str(e)
        # Minimal fallback response so the page still loads with defaults.
        # Do NOT reuse the original context values that may have caused the
        # render failure; start from safe defaults and only keep known-safe
        # scalar metadata.
        fallback_context = _default_premium_context()
        fallback_context["request"] = request
        fallback_context["render_error"] = render_error
        fallback_context["data_source"] = source
        fallback_context["subnets"] = subnets if isinstance(subnets, list) else []
        try:
            return templates.TemplateResponse("index.html", fallback_context)
        except Exception as e2:
            logger.error("Fallback dashboard render also failed: %s\n%s", e2, traceback.format_exc())
            return PlainTextResponse(
                f"RENDER ERROR: {render_error}\n\nFALLBACK ERROR: {e2}\n\nFULL TRACEBACK:\n{traceback.format_exc()}",
                status_code=500,
            )



@router.get("/api/predictions")
async def api_predictions():
    """Return pending + resolved predictions from the predictive engine.

    All entries use the predictive framing: 'predicted to move +X% within N hours'.
    Resolved entries carry actual_pct + correctness for the learning loop.
    """
    try:
        data = PREDICTION_STORE._load()
        PREDICTION_STORE.update_stats(data)
        PREDICTION_STORE._save(data)
        return {
            "predictions": data.get("predictions", []),
            "resolved": data.get("resolved", []),
            "stats": data.get("stats", {}),
        }
    except Exception as e:
        logger.error("Error fetching predictions: %s", e)
        return {"predictions": [], "resolved": [], "stats": {}, "error": str(e)}



@router.get("/api/predictions/resolved")
async def api_predictions_resolved(resolve: bool = False):
    """Return resolved predictions. Trigger a 24h resolution pass when ``resolve=1``."""
    try:
        if resolve:
            subnets, _ = _get_subnets_with_source()
            result = resolver.resolve_due_predictions(subnets)
        else:
            result = resolver.get_resolved_predictions()
        return {
            "status": "ok",
            "resolved": result.get("resolved", []),
            "stats": result.get("stats", {}),
            "triggered_resolution": resolve,
        }
    except Exception as e:
        logger.error("Error resolving predictions: %s", e)
        return {"status": "error", "resolved": [], "stats": {}, "error": str(e)}



@router.get("/api/rotation-tracker")
async def api_rotation_tracker():
    """Return subnet rotation patterns and volatility clusters."""
    try:
        subnets, _ = _get_subnets_with_source()
        _mark_fresh("rotation")
        return {"status": "ok", **rotation_tracker.get_rotation_summary(subnets)}
    except Exception as e:
        logger.error("Error fetching rotation tracker: %s", e)
        return {"status": "error", "patterns": [], "volatility_clusters": {}, "error": str(e)}



@router.get("/api/daily-pick")
async def api_daily_pick():
    """Return today's audited daily pick from the Council engine."""
    try:
        subnets, _ = _get_subnets_with_source()
        # Use the same real market-wide mood proxy as the homepage so the
        # daily pick stays in sync with the rendered dashboard.
        market_context = {"tao_change_24h": _market_mood_proxy(subnets)}
        _mark_fresh("top_pick_day")
        return get_or_create_today_pick(subnets, market_context)
    except Exception as e:
        logger.error("Error fetching daily pick: %s", e)
        return {
            "status": "error",
            "date": datetime.utcnow().date().isoformat(),
            "action": "HOLD",
            "reason": str(e),
            "pick": None,
        }



