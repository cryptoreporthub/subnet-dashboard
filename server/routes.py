"""All API and web routes."""
import traceback
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from server.config import *  # noqa: F403
from server_original import (
    _build_fallback_picks,
    _build_premium_context,
    _default_learning_metrics,
    _default_market_intelligence,
    _default_premium_context,
    _default_rotation_tracker,
    _default_scenario_memory,
    _enrich_pick_scenario,
    _fallback_state_pick,
    _latest_scenario_by_name,
    _market_mood_proxy,
    _ordered_hour_picks,
    _record_pick_scenario,
    api_indicators_convergence,
    api_rotation_tracker,
    api_scenario_memory,
    get_learning_stats,
    get_mindmap_summary,
    get_or_create_today_pick,
    get_simivision_data,
)

import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
def health_check():
    return PlainTextResponse("OK")


@router.get("/api/health")
def api_health_check():
    """JSON health probe for Fly.io / monitoring tooling."""
    return {"status": "ok"}


@router.get("/api/freshness")
def api_freshness():
    """Per-section 'last updated' timestamps for the dashboard freshness badges."""
    return _freshness_snapshot()


@router.get("/api/pick-history")
def api_pick_history():
    """Pick-of-the-Hour history + aggregate success metric."""
    return _hour_pick_history(limit=20)


@router.get("/", response_class=HTMLResponse)
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
        return templates.TemplateResponse(request, "index.html", context)
    except Exception as e:
        logger.error("Error rendering dashboard template: %s\n%s", e, traceback.format_exc())
        render_error = str(e)
        # Minimal fallback response so the page still loads with defaults.
        # Do NOT reuse the original context values that may have caused the
        # render failure; start from safe defaults and only keep known-safe
        # scalar metadata.
        fallback_context = _default_premium_context()
        fallback_context["render_error"] = render_error
        fallback_context["data_source"] = source
        fallback_context["subnets"] = subnets if isinstance(subnets, list) else []
        try:
            return templates.TemplateResponse(request, "index.html", fallback_context)
        except Exception as e2:
            logger.error("Fallback dashboard render also failed: %s\n%s", e2, traceback.format_exc())
            return PlainTextResponse(
                f"RENDER ERROR: {render_error}\n\nFALLBACK ERROR: {e2}\n\nFULL TRACEBACK:\n{traceback.format_exc()}",
                status_code=500,
            )
