"""Routes: system — 45 endpoint(s)."""
from fastapi import APIRouter
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



@router.get("/api/subnets")
def api_subnets_safe():
    subnets, source = _get_subnets_with_source()
    return {
        "status": "success",
        "meta": {
            "count": len(subnets),
            "source": source,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        },
        "subnets": subnets,
    }



@router.get("/api/simivision")
def api_simivision_safe():
    return _safe_simivision_payload()



@router.get("/api/rotation-tokens")
def api_rotation_tokens_safe():
    """Return the rotation-token watchlist with live CoinGecko prices.

    Each token includes its symbol, a display label, and the current USD price
    plus 24h change fetched from CoinGecko (cached for 60 seconds).  When the
    live price feed is unavailable we fall back to the last cached value so the
    watchlist endpoint stays useful.
    """
    prices = _fetch_rotation_token_prices()
    tokens = []
    for symbol in _ROTATION_TOKENS:
        entry = prices.get(symbol, {}) if isinstance(prices, dict) else {}
        price = entry.get("price")
        change = entry.get("price_change_24h")
        tokens.append({
            "symbol": symbol.upper(),
            "name": symbol.title(),
            "price": price,
            "price_change_24h": change,
            "source": "coingecko" if price is not None else "watchlist",
        })
    return {
        "status": "success",
        "tokens": tokens,
    }



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



@router.get("/api/indicators/scheduler")
def api_indicators_scheduler():
    """Return the current state of the background indicator scheduler."""
    return {
        "status": "success",
        "data": get_indicator_scheduler_state(),
    }



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



@router.get("/api/learning-metrics")
async def api_learning_metrics():
    """Return learning-loop metrics: expert weights, accuracy, recent resolutions."""
    try:
        return _compute_learning_metrics()
    except Exception as e:
        logger.error("Error fetching learning metrics: %s", e)
        return {"error": str(e), "expert_weights": {}, "accuracy": 0.0}



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



