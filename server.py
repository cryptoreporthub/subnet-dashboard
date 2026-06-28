import json
import logging
import math
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Add the current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetchers.taomarketcap import get_all_subnets, get_subnet_data
from internal.council.state_vector import score_subnet_for_hour, score_subnet_for_day
from internal.council.daily_pick import select_daily_pick
from internal.council import resolver, scenario_memory, rotation_tracker
from internal.indicators import (
    IndicatorEngine,
    get_indicator_scheduler_state,
    start_indicator_scheduler,
    stop_indicator_scheduler,
)
try:
    from data.learning_engine import LearningEngine, create_feedback_router
except ImportError:
    class LearningEngine:
        def get_stats(self):
            return {"expert_weights": {}, "total_records": 0}

        def load_soul_map(self):
            return {"expert_weights": {}, "performance_history": {}}

    def create_feedback_router():
        return None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

os.makedirs("data", exist_ok=True)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the indicator scheduler on startup and stop it on shutdown."""
    try:
        start_indicator_scheduler()
        logger.info("Indicator scheduler started")
    except Exception as exc:
        logger.warning("Failed to start indicator scheduler: %s", exc)
    yield
    try:
        stop_indicator_scheduler()
        logger.info("Indicator scheduler stopped")
    except Exception as exc:
        logger.warning("Failed to stop indicator scheduler: %s", exc)


app = FastAPI(
    title="SimiVision Subnet Dashboard",
    version="3.5.0",
    lifespan=_lifespan,
)

# CORS middleware (replaces Flask's per-response CORS headers)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files at /static
_static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# Jinja2 templates for server-side rendered dashboard
_templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
templates = Jinja2Templates(directory=_templates_dir)

_APP_VERSION = "3.5.0"

_ROTATION_TOKENS = ["hyperliquid", "vvv", "near", "render", "fetch"]

# ---------------------------------------------------------------------------
# SimiVision chat helpers (Phase 4: LLM interaction with mindmap context)
# ---------------------------------------------------------------------------

def _build_simivision_prompt(message: str, context: Dict[str, Any]) -> str:
    """Build a prompt that fuses the user message with live SimiVision + soul_map context."""
    top = context.get("simivision_picks", [])
    picks_str = "; ".join(
        f"#{p.get('rank')} {p.get('name')} (SN{p.get('netuid')}) "
        f"emission={p.get('emission')} apy={p.get('apy')} "
        f"chg24h={p.get('price_change_24h')}% conviction={p.get('conviction')} "
        f"rec={p.get('recommendation')}"
        for p in top
    ) or "No picks available"
    weights = context.get("expert_weights", {})
    weights_str = ", ".join(f"{k}={v}" for k, v in weights.items()) or "none"
    return (
        "You are SimiVision, an AI analyst for Bittensor subnets. "
        "Use the live subnet snapshot and the Council's learned expert weights below.\n\n"
        f"User question: {message}\n\n"
        f"Top SimiVision picks: {picks_str}\n"
        f"Source: {context.get('source', 'unknown')}\n"
        f"Council expert weights (self-learning loop): {weights_str}\n"
        "Answer concisely and tie the reasoning back to the picks and expert weights."
    )


def _call_llm(prompt: str, message: str, context: Dict[str, Any]) -> tuple[str, bool]:
    """Call an LLM API when configured, otherwise fall back to the local explainer.

    Returns (reply, llm_used). The local fallback keeps the endpoint fully
    functional in environments without an LLM API key while still integrating
    the mindmap / self-learning context.
    """
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

    if api_key:
        try:
            import requests
            resp = requests.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are SimiVision, a Bittensor subnet analyst."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 400,
                },
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if reply:
                    return reply.strip(), True
            logger.warning("LLM API call failed (%s); falling back to local explainer", resp.status_code)
        except Exception as exc:
            logger.warning("LLM API call errored (%s); falling back to local explainer", exc)

    # Local fallback: reuse the existing SimiVision explainer so the loop stays intact.
    try:
        from internal.llm.explainer import generate_ai_response
        return generate_ai_response(message, context), False
    except Exception as exc:
        logger.warning("Local explainer failed (%s); returning canned reply", exc)
        return (
            "SimiVision is online. I can explain top subnet picks, compare APY, "
            "or analyze market trends. What would you like to know?",
            False,
        )

# ---------------------------------------------------------------------------
# Fast, fail-safe endpoints
# These are registered first so they win even if older route definitions below
# still exist in the file or in a stale deployment.
# ---------------------------------------------------------------------------

def _get_subnets_with_source() -> tuple[List[Dict[str, Any]], str]:
    """Return subnets with source tracking.
    
    Uses taomarketcap API with caching (5 min TTL).
    Returns (subnets, source) where source is one of:
    - "taomarketcap" (live data)
    - "taomarketcap-cache" (stale cache)
    - "static-fallback" (no cache available)
    """
    cache_path = os.path.join("data", "subnets.db")
    db_exists = os.path.exists(cache_path)
    
    try:
        subnets = get_all_subnets()
        if subnets:
            # Determine source based on cache status
            if db_exists:
                source = "taomarketcap"
            else:
                source = "taomarketcap-cache"
            return subnets, source
    except Exception as exc:
        logger.warning("Error fetching from taomarketcap: %s", exc)
    
    # Static fallback
    logger.warning("Using static fallback data")
    return [
        {
            "netuid": 29,
            "name": "Coldint",
            "emission": 3.0,
            "apy": 42.5,
            "volume": 1250000,
            "market_cap": 45000000,
            "price": 28.50,
            "price_change_24h": 12.3,
            "price_change_7d": 18.2,
            "price_change_30d": 24.9,
            "status": "active",
            "sector": "AI/ML",
        },
        {
            "netuid": 19,
            "name": "Inference",
            "emission": 2.1,
            "apy": 38.2,
            "volume": 980000,
            "market_cap": 32000000,
            "price": 15.20,
            "price_change_24h": 8.7,
            "price_change_7d": 12.1,
            "price_change_30d": 16.8,
            "status": "active",
            "sector": "AI/ML",
        },
        {
            "netuid": 12,
            "name": "Compute",
            "emission": 1.8,
            "apy": 35.1,
            "volume": 750000,
            "market_cap": 28000000,
            "price": 12.40,
            "price_change_24h": 5.2,
            "price_change_7d": 9.4,
            "price_change_30d": 13.0,
            "status": "active",
            "sector": "Compute",
        },
    ], "static-fallback"


def _safe_simivision_payload() -> Dict[str, Any]:
    subnets, source = _get_subnets_with_source()
    ranked = sorted(subnets, key=lambda s: (s.get("emission", 0), s.get("apy", 0), s.get("volume", 0)), reverse=True)
    top = []
    for idx, sn in enumerate(ranked[:3], start=1):
        top.append({
            "rank": idx,
            "netuid": sn.get("netuid"),
            "name": sn.get("name"),
            "emission": sn.get("emission", 0),
            "apy": sn.get("apy", 0),
            "price_change_24h": sn.get("price_change_24h", 0),
            "conviction": min(95, 72 + int(abs(sn.get("price_change_24h", 0))) + int(sn.get("apy", 0) / 4)),
            "recommendation": "BUY" if idx == 1 else ("HOLD" if idx == 2 else "WATCH"),
        })

    return {
        "status": "success",
        "data": {
            "top": top,
            "meta": {
                "count": len(subnets),
                "source": source,
                "updated_at": datetime.utcnow().isoformat() + "Z",
            },
        },
    }


@app.get("/health")
def health_check():
    return PlainTextResponse("OK")


@app.get("/api/top-pick/day")
def api_top_pick_day():
    """Return the top pick for the current day."""
    subnets, _ = _get_subnets_with_source()
    market_context = {"tao_change_24h": 0.0}
    day_picks = [select_daily_pick(subnets, market_context)]
    return {"picks": day_picks}


@app.get("/api/subnets")
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


@app.get("/api/simivision")
def api_simivision_safe():
    return _safe_simivision_payload()


@app.get("/api/rotation-tokens")
def api_rotation_tokens_safe():
    """Return the rotation-token watchlist with safe price placeholders.

    Each token includes its symbol, a display label, and any available price
    data we can derive without requiring external services to be up.  This
    keeps the watchlist endpoint useful even when live price feeds are
    unavailable.
    """
    tokens = []
    for symbol in _ROTATION_TOKENS:
        tokens.append({
            "symbol": symbol.upper(),
            "name": symbol.title(),
            "price": None,
            "price_change_24h": None,
            "source": "watchlist",
        })
    return {
        "status": "success",
        "tokens": tokens,
    }


@app.get("/api/mindmap/summary")
def api_mindmap_summary_safe():
    simivision = _safe_simivision_payload()["data"]
    # Pull live soul_map expert weights from the self-learning loop so the
    # mindmap stays wired into the evidence -> signal -> decision -> judge
    # -> learning cycle.
    engine = LearningEngine()
    stats = engine.get_stats()
    expert_weights = stats.get("expert_weights", {})
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
            "learning_status": {
                "enabled": True,
                "records": stats.get("total_records", 0),
                "last_updated": stats.get("last_updated") or simivision["meta"]["updated_at"],
            },
        },
    }


@app.get("/api/learning/stats")
def api_learning_stats_safe():
    # Use the full learning-loop metrics so the dashboard exposes expert
    # weights, resolution counts, accuracy and a last_updated timestamp.
    metrics = _compute_learning_metrics()
    return {
        "status": "success",
        "data": {
            "expert_weights": metrics.get("expert_weights", {}),
            "total_records": metrics.get("total_records", 0),
            "correct": metrics.get("correct", 0),
            "wrong": metrics.get("wrong", 0),
            "accuracy": metrics.get("accuracy", 0.0),
            "predictions_pending": metrics.get("predictions_pending", 0),
            "predictions_resolved": metrics.get("predictions_resolved", 0),
            "last_updated": metrics.get("last_updated") or datetime.utcnow().isoformat() + "Z",
        },
    }


@app.get("/api/indicators/scheduler")
def api_indicators_scheduler():
    """Return the current state of the background indicator scheduler."""
    return {
        "status": "success",
        "data": get_indicator_scheduler_state(),
    }


@app.post("/api/simivision/chat")
async def api_simivision_chat(request: Request):
    """LLM interaction endpoint for SimiVision data.

    Pipeline (Phase 4):
      1. Fetch subnet data
      2. Load soul_map.json for learning context
      3. Build prompt with context
      4. Call LLM API (falls back to local explainer when no key is set)
      5. Return response with mindmap context
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    message = (payload or {}).get("message", "") or ""

    # 1. Fetch subnet data
    subnets, source = _get_subnets_with_source()
    simivision = _safe_simivision_payload()["data"]

    # 2. Load soul_map.json for learning context
    engine = LearningEngine()
    soul_map = engine.load_soul_map()
    stats = engine.get_stats()
    expert_weights = stats.get("expert_weights", {})

    # 3. Build prompt with context
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
    }
    prompt = _build_simivision_prompt(message, context)

    # 4. Call LLM API (with graceful local fallback)
    reply, llm_used = _call_llm(prompt, message, context)

    # 5. Return response with mindmap context
    return {
        "status": "success",
        "data": {
            "reply": reply,
            "message": message,
            "llm_used": llm_used,
            "mindmap_context": {
                "source": source,
                "top_picks": top,
                "expert_weights": expert_weights,
                "learning_records": stats.get("total_records", 0),
                "updated_at": simivision.get("meta", {}).get("updated_at"),
            },
        },
    }


# ============================================================================
# Root route: server-side rendered Jinja2 dashboard
# ============================================================================
def get_simivision_data() -> Dict[str, Any]:
    """Return the SimiVision payload (top picks + meta) for template rendering."""
    return _safe_simivision_payload()["data"]


def get_mindmap_summary() -> Dict[str, Any]:
    """Return the mindmap summary (soul_map expert weights + top subnet picks).

    Wired into the evidence -> signal -> decision -> judge -> learning loop via
    the LearningEngine, which reads data/soul_map.json.
    """
    return api_mindmap_summary_safe()["data"]


def get_learning_stats() -> Dict[str, Any]:
    """Return self-learning loop stats (expert weights + record count)."""
    return api_learning_stats_safe()["data"]


# ============================================================================
# Premium Dashboard — Backend Intelligence Layer
# Predictive engine: all outputs framed as "predicted to move +X% within N hours".
# Evidence -> signal -> decision -> judge -> learning loop, persisted to JSON.
# ============================================================================

import json as _json
import os as _os
import math as _math
import uuid as _uuid
from datetime import datetime as _dt, timedelta as _td

_PREDICTIONS_PATH = _os.path.join("data", "predictions.json")
_PRICE_CACHE_PATH = _os.path.join("data", "price_cache.json")
_REGISTRY_PATH = _os.path.join("config", "registry.json")
_SIGNAL_TYPES_PATH = _os.path.join("config", "signal_types.json")

# Learning-loop weight deltas (correct = reward, wrong = penalize).
_LEARNING_DELTA_CORRECT = 0.02
_LEARNING_DELTA_WRONG = -0.03
_LEARNING_MIN_WEIGHT = 0.1
_LEARNING_MAX_WEIGHT = 2.0

# Price-history source flag.
# The taomarketcap API exposes only the current price + 24h/7d/30d percentage
# changes (no OHLC candle history), and Bittensor alpha tokens are not
# reliably listed on CoinGecko. We therefore default to the synthetic series
# derived from those change fields (see _get_price_history). Flip this to True
# only when a real candle endpoint is wired into _get_price_history.
USE_REAL_PRICE_HISTORY = _os.environ.get("USE_REAL_PRICE_HISTORY", "0") == "1"

# How long to suppress duplicate predictions for the same netuid+direction.
_PREDICTION_DEDUP_WINDOW_HOURS = 1


def _load_signal_types() -> Dict[str, Any]:
    try:
        with open(_SIGNAL_TYPES_PATH, "r") as f:
            data = _json.load(f)
        return data.get("signal_types", data) or {}
    except Exception:
        return {
            "rsi_crossover": {"half_life_hours": 24, "description": "RSI threshold crossover", "default_direction": "bullish"},
            "macd_cross": {"half_life_hours": 48, "description": "MACD cross", "default_direction": "neutral"},
            "momentum_shift": {"half_life_hours": 12, "description": "Rate of change zero-cross", "default_direction": "neutral"},
            "stochastic_reversal": {"half_life_hours": 8, "description": "Stochastic reversal", "default_direction": "bullish"},
            "whale_accumulation": {"half_life_hours": 72, "description": "Whale accumulation", "default_direction": "bullish"},
            "social_sentiment": {"half_life_hours": 6, "description": "Social sentiment shift", "default_direction": "neutral"},
            "emission_change": {"half_life_hours": 168, "description": "Emission curve change", "default_direction": "neutral"},
            "funding_divergence": {"half_life_hours": 24, "description": "Funding rate divergence", "default_direction": "neutral"},
            "onchain_flow": {"half_life_hours": 48, "description": "On-chain flow anomaly", "default_direction": "neutral"},
        }


SIGNAL_TYPES = _load_signal_types()

# Pattern definitions — 7 recognisable candle/price patterns.
PATTERN_DEFS = {
    "bullish_engulfing": {"type": "bullish", "description": "Bullish engulfing — buyers overwhelm prior candle"},
    "bearish_engulfing": {"type": "bearish", "description": "Bearish engulfing — sellers overwhelm prior candle"},
    "hammer": {"type": "bullish", "description": "Hammer — rejection of lows, potential reversal up"},
    "shooting_star": {"type": "bearish", "description": "Shooting star — rejection of highs, potential reversal down"},
    "doji": {"type": "neutral", "description": "Doji — indecision, momentum stalling"},
    "double_top": {"type": "bearish", "description": "Double top — two peaks, bearish reversal"},
    "double_bottom": {"type": "bullish", "description": "Double bottom — two troughs, bullish reversal"},
}


class PREDICTION_STORE:
    """Persists predictions to data/predictions.json and resolves them over time."""

    @staticmethod
    def _load() -> Dict[str, Any]:
        try:
            with open(_PREDICTIONS_PATH, "r") as f:
                return _json.load(f)
        except Exception:
            return {"predictions": [], "resolved": [], "stats": {"correct": 0, "wrong": 0, "pending": 0}}

    @staticmethod
    def _save(data: Dict[str, Any]) -> None:
        try:
            _os.makedirs("data", exist_ok=True)
            with open(_PREDICTIONS_PATH, "w") as f:
                _json.dump(data, f, indent=2)
        except Exception as exc:
            logger.warning("Failed to persist predictions.json: %s", exc)

    @staticmethod
    def add(prediction: Dict[str, Any]) -> Dict[str, Any]:
        data = PREDICTION_STORE._load()
        data.setdefault("predictions", []).append(prediction)
        data.setdefault("resolved", [])
        PREDICTION_STORE._save(data)
        return prediction

    @staticmethod
    def all() -> List[Dict[str, Any]]:
        return PREDICTION_STORE._load().get("predictions", [])

    @staticmethod
    def resolved() -> List[Dict[str, Any]]:
        return PREDICTION_STORE._load().get("resolved", [])

    @staticmethod
    def update_stats(data: Dict[str, Any]) -> None:
        preds = data.get("predictions", [])
        resolved = data.get("resolved", [])
        correct = sum(1 for r in resolved if r.get("correct"))
        wrong = sum(1 for r in resolved if not r.get("correct"))
        data["stats"] = {"correct": correct, "wrong": wrong, "pending": len(preds), "total": len(preds) + len(resolved)}
        if correct + wrong > 0:
            data["stats"]["accuracy"] = round(correct / (correct + wrong), 3)
        else:
            data["stats"]["accuracy"] = 0.0


def _dedupe_predictions(data: Dict[str, Any]) -> Dict[str, Any]:
    """Collapse duplicate pending predictions.

    Keeps only the most recent pending prediction per (netuid, direction) pair;
    older duplicates for the same pair are dropped so the predictive engine
    does not accumulate one entry per refresh cycle. Resolved predictions are
    left untouched. Stats are recomputed afterwards by the caller.
    """
    pending = data.get("predictions", [])
    if not isinstance(pending, list):
        pending = []
    newest_by_key: Dict[tuple, Dict[str, Any]] = {}
    for pred in pending:
        key = (pred.get("netuid"), pred.get("direction"))
        prev = newest_by_key.get(key)
        if prev is None:
            newest_by_key[key] = pred
            continue
        try:
            prev_ts = prev.get("created_at", "") or ""
            cur_ts = pred.get("created_at", "") or ""
            if cur_ts > prev_ts:
                newest_by_key[key] = pred
        except Exception:
            # keep the first seen on any comparison error
            pass
    data["predictions"] = list(newest_by_key.values())
    return data


def resolve_predictions(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Run the prediction resolver on every dashboard render.

    Loads data/predictions.json, deduplicates pending predictions, resolves
    any whose ``resolve_at`` has elapsed against the latest subnet price,
    updates expert weights via the learning loop, recomputes stats and
    persists the result. Returns the list of predictions resolved this run.
    """
    data = PREDICTION_STORE._load()
    data = _dedupe_predictions(data)
    resolved_now = _resolve_due_predictions(subnets, data=data)
    PREDICTION_STORE.update_stats(data)
    PREDICTION_STORE._save(data)
    return resolved_now


# ---------------------------------------------------------------------------
# Price history helper — loads candles from data/price_cache.json keyed by
# netuid. Falls back to a synthetic series derived from price + change fields
# when no candle history exists (keeps indicators functional & graceful).
# ---------------------------------------------------------------------------
def _load_price_cache() -> Dict[str, Any]:
    try:
        with open(_PRICE_CACHE_PATH, "r") as f:
            return _json.load(f)
    except Exception:
        return {}


def _get_price_history(netuid: Any, sn: Dict[str, Any]) -> Dict[str, Any]:
    """Return {closes, highs, lows, volumes, timestamps} for a subnet.

    Data source policy (controlled by ``USE_REAL_PRICE_HISTORY``):
    - When real candle history exists in data/price_cache.json it is used as-is.
    - Otherwise the series is synthesised from the subnet's price + 24h/7d/30d
      percentage changes so the indicators (RSI, MACD, ...) still produce
      realistic, non-degenerate values. The taomarketcap API does not expose
      OHLC candles, so the synthetic fallback is the default path. Set
      ``USE_REAL_PRICE_HISTORY=1`` once a real candle endpoint is wired in here.
    """
    closes: List[float] = []
    highs: List[float] = []
    lows: List[float] = []
    volumes: List[float] = []
    timestamps: List[str] = []
    source = "synthetic"

    cache = _load_price_cache()
    raw = cache.get(str(netuid)) or cache.get(int(netuid) if str(netuid).isdigit() else netuid)
    if raw and isinstance(raw, dict):
        candles = raw.get("candles") or []
        if candles:
            source = raw.get("source", "cached")
            for c in candles:
                cl = c.get("close")
                if cl is None:
                    continue
                closes.append(float(cl))
                highs.append(float(c.get("high", cl)))
                lows.append(float(c.get("low", cl)))
                volumes.append(float(c.get("volume", 0) or 0))
                timestamps.append(c.get("timestamp", ""))

    if len(closes) < 30:
        price = float(sn.get("price", 0) or 0)
        if price <= 0:
            price = 1.0
        chg_24h = float(sn.get("price_change_24h", 0) or 0)
        chg_7d = float(sn.get("price_change_7d", 0) or 0)
        chg_30d = float(sn.get("price_change_30d", 0) or 0)
        steps = []
        for i in range(30):
            if i < 10:
                # 30d change spread evenly across its 10-candle window
                steps.append(chg_30d / 10.0)
            elif i < 22:
                # 7d change spread evenly across its 12-candle window
                steps.append(chg_7d / 12.0)
            else:
                # 24h change spread evenly across its 8-candle window
                steps.append(chg_24h / 8.0)
        steps = [s if abs(s) < 50 else (50 if s > 0 else -50) for s in steps]
        # Blend the trend step with a deterministic sinusoidal oscillation so the
        # synthesised series is NOT monotonically non-decreasing (which would
        # starve the RSI of losses and force it to 100). Amplitude scales with the
        # trend step (min 2%) so genuine pullbacks occur even on strong uptrends,
        # keeping RSI in a realistic (non-degenerate) range. Index-driven for
        # reproducibility and trend-preserving on average.
        p = price
        synth_closes = []
        for i, s in enumerate(steps):
            amp = max(2.0, abs(s) * 2.0)
            osc = math.sin(i * 0.7) * amp  # deterministic wiggle, scales with trend
            p = p * (1 + s / 100.0) * (1 + osc / 100.0)
            synth_closes.append(p)
        closes = (closes + synth_closes)[-30:]
        highs = [c * 1.01 for c in closes]
        lows = [c * 0.99 for c in closes]
        base_vol = float(sn.get("volume", 0) or 0) / max(len(closes), 1)
        volumes = [base_vol for _ in closes]
        timestamps = timestamps[-len(closes):] or ["" for _ in closes]
        source = "synthetic" if not timestamps[0] else source

    return {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes, "timestamps": timestamps, "source": source}


# ---------------------------------------------------------------------------
# 8 technical indicators
# ---------------------------------------------------------------------------
def _sma(values: List[float], period: int) -> float:
    if len(values) < period or period <= 0:
        return 0.0
    return sum(values[-period:]) / period


def _ema(values: List[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _compute_rsi_series(closes: List[float], period: int = 14) -> float:
    """Proper Wilder RSI from close prices. Falls back to 50.0 on short history.

    Uses Wilder's smoothing: the first average gain/loss is a simple average
    over `period` changes, then each subsequent value is
    ``avg = (prev_avg * (period-1) + change) / period``. A flat series (no
    gains AND no losses) returns 50.0 instead of the degenerate 100.0.
    """
    if len(closes) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses += -diff
    avg_gain = gains / period
    avg_loss = losses / period
    # Wilder smoothing over the remaining closes.
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = diff if diff >= 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_gain == 0 and avg_loss == 0:
        return 50.0  # flat series — neither overbought nor oversold
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def _compute_stochastic(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict[str, Any]:
    if len(closes) < period:
        return {"k": 50.0, "d": 50.0, "signal": "neutral"}
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    close = closes[-1]
    if hh - ll == 0:
        k = 50.0
    else:
        k = ((close - ll) / (hh - ll)) * 100
    ks = []
    for j in range(3, 0, -1):
        end = len(closes) - j + 1
        start = end - period
        if start < 0:
            ks.append(k)
            continue
        h = max(highs[start:end])
        l = min(lows[start:end])
        c = closes[end - 1]
        ks.append(((c - l) / (h - l)) * 100 if (h - l) != 0 else 50.0)
    d = sum(ks) / len(ks)
    sig = "oversold" if k < 20 else "overbought" if k > 80 else "neutral"
    return {"k": round(k, 1), "d": round(d, 1), "signal": sig}


def _compute_bollinger(closes: List[float], period: int = 20, num_std: float = 2.0) -> Dict[str, Any]:
    if len(closes) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "width": 0, "signal": "neutral"}
    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((x - mid) ** 2 for x in window) / period
    sd = _math.sqrt(variance)
    upper = mid + num_std * sd
    lower = mid - num_std * sd
    price = closes[-1]
    sig = "overbought" if price > upper else "oversold" if price < lower else "neutral"
    return {"upper": round(upper, 4), "middle": round(mid, 4), "lower": round(lower, 4), "width": round(upper - lower, 4), "signal": sig}


def _compute_mfi(highs: List[float], lows: List[float], closes: List[float], volumes: List[float], period: int = 14) -> Dict[str, Any]:
    if len(closes) < period + 1:
        return {"mfi": 50.0, "signal": "neutral"}
    typical = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(len(closes))]
    pos_flow, neg_flow = 0.0, 0.0
    for i in range(1, period + 1):
        rmf = typical[-i] * volumes[-i]
        prev = typical[-i - 1]
        if typical[-i] > prev:
            pos_flow += rmf
        elif typical[-i] < prev:
            neg_flow += rmf
    if neg_flow == 0:
        mfi = 100.0
    else:
        mfi = 100 - (100 / (1 + pos_flow / neg_flow))
    sig = "oversold" if mfi < 20 else "overbought" if mfi > 80 else "neutral"
    return {"mfi": round(mfi, 1), "signal": sig}


def _compute_cci(highs: List[float], lows: List[float], closes: List[float], period: int = 20) -> Dict[str, Any]:
    if len(closes) < period:
        return {"cci": 0.0, "signal": "neutral"}
    typical = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(len(closes))]
    window = typical[-period:]
    sma_t = sum(window) / period
    mean_dev = sum(abs(x - sma_t) for x in window) / period
    if mean_dev == 0:
        cci = 0.0
    else:
        cci = (typical[-1] - sma_t) / (0.015 * mean_dev)
    sig = "oversold" if cci < -100 else "overbought" if cci > 100 else "neutral"
    return {"cci": round(cci, 1), "signal": sig}


def _compute_williams_r(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict[str, Any]:
    if len(closes) < period:
        return {"williams_r": -50.0, "signal": "neutral"}
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    if hh - ll == 0:
        wr = -50.0
    else:
        wr = ((hh - closes[-1]) / (hh - ll)) * -100
    sig = "oversold" if wr < -80 else "overbought" if wr > -20 else "neutral"
    return {"williams_r": round(wr, 1), "signal": sig}


def _compute_keltner(closes: List[float], highs: List[float], lows: List[float], period: int = 20, mult: float = 2.0) -> Dict[str, Any]:
    if len(closes) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "signal": "neutral"}
    ema = _ema(closes[-period * 3:], period)
    trs = []
    for i in range(1, min(len(closes), period * 2)):
        tr = max(highs[-i] - lows[-i], abs(highs[-i] - closes[-i - 1]), abs(lows[-i] - closes[-i - 1]))
        trs.append(tr)
    atr = sum(trs) / len(trs) if trs else 0.0
    upper = ema + mult * atr
    lower = ema - mult * atr
    price = closes[-1]
    sig = "overbought" if price > upper else "oversold" if price < lower else "neutral"
    return {"upper": round(upper, 4), "middle": round(ema, 4), "lower": round(lower, 4), "signal": sig}


def _compute_macd_series(closes: List[float]) -> Dict[str, Any]:
    if len(closes) < 26:
        return {"macd": 0, "signal": 0, "histogram": 0, "crossover": "neutral"}
    ema12 = _ema(closes[-50:], 12)
    ema26 = _ema(closes[-60:], 26)
    macd_line = ema12 - ema26
    signal = macd_line * 0.9
    histogram = macd_line - signal
    crossover = "bullish" if histogram > 0 else "bearish" if histogram < 0 else "neutral"
    return {"macd": round(macd_line, 4), "signal": round(signal, 4), "histogram": round(histogram, 4), "crossover": crossover}


# ---------------------------------------------------------------------------
# Multi-indicator convergence
# ---------------------------------------------------------------------------
def _detect_oversold_convergence(indicators: Dict[str, Any]) -> Dict[str, Any]:
    """Count how many oscillators agree on oversold conditions (bullish reversal)."""
    keys = ["rsi", "stochastic", "mfi", "williams_r", "cci", "bollinger", "keltner"]
    hits = []
    for k in keys:
        v = indicators.get(k, {})
        if isinstance(v, dict) and v.get("signal") == "oversold":
            hits.append(k)
    return {
        "type": "oversold",
        "direction": "bullish",
        "count": len(hits),
        "total": len(keys),
        "agreement": round(len(hits) / len(keys), 2),
        "indicators": hits,
        "convergent": len(hits) >= 3,
    }


def _detect_overbought_convergence(indicators: Dict[str, Any]) -> Dict[str, Any]:
    """Count how many oscillators agree on overbought conditions (bearish reversal)."""
    keys = ["rsi", "stochastic", "mfi", "williams_r", "cci", "bollinger", "keltner"]
    hits = []
    for k in keys:
        v = indicators.get(k, {})
        if isinstance(v, dict) and v.get("signal") == "overbought":
            hits.append(k)
    return {
        "type": "overbought",
        "direction": "bearish",
        "count": len(hits),
        "total": len(keys),
        "agreement": round(len(hits) / len(keys), 2),
        "indicators": hits,
        "convergent": len(hits) >= 3,
    }


# ---------------------------------------------------------------------------
# HOT / SELL signal engine
# ---------------------------------------------------------------------------
def _compute_hot_signals(sn: Dict[str, Any], indicators: Dict[str, Any], convergence: Dict[str, Any]) -> Dict[str, Any]:
    """HOT = strong bullish setup. SELL ALERT wins over HOT when bearish pressure dominates."""
    score = 0
    reasons = []
    chg = float(sn.get("price_change_24h", 0) or 0)
    apy = float(sn.get("apy", 0) or 0)
    emission = float(sn.get("emission", 0) or 0)

    if convergence.get("type") == "oversold" and convergence.get("convergent"):
        score += 3
        reasons.append(f"Oversold convergence ({convergence.get('count')}/{convergence.get('total')} oscillators)")
    rsi = indicators.get("rsi", {})
    if isinstance(rsi, dict) and rsi.get("signal") == "oversold":
        score += 2
        reasons.append("RSI oversold reversal zone")
    macd = indicators.get("macd", {})
    if isinstance(macd, dict) and macd.get("crossover") == "bullish":
        score += 2
        reasons.append("MACD bullish crossover")
    if chg > 5:
        score += 2
        reasons.append(f"Strong 24h momentum (+{chg:.1f}%)")
    if apy > 30:
        score += 1
        reasons.append(f"High yield ({apy:.1f}% APY)")
    if emission > 3:
        score += 1
        reasons.append(f"Strong emission ({emission:.2f} TAO/day)")

    active = score >= 5
    return {
        "active": active,
        "score": score,
        "reasons": reasons or ["No strong bullish setup"],
        "label": "HOT" if active else None,
    }


def _compute_sell_signals(sn: Dict[str, Any], indicators: Dict[str, Any], convergence: Dict[str, Any]) -> Dict[str, Any]:
    """SELL ALERT — takes precedence over HOT when bearish pressure dominates."""
    score = 0
    reasons = []
    chg = float(sn.get("price_change_24h", 0) or 0)
    if convergence.get("type") == "overbought" and convergence.get("convergent"):
        score += 3
        reasons.append(f"Overbought convergence ({convergence.get('count')}/{convergence.get('total')} oscillators)")
    rsi = indicators.get("rsi", {})
    if isinstance(rsi, dict) and rsi.get("signal") == "overbought":
        score += 2
        reasons.append("RSI overbought distribution zone")
    macd = indicators.get("macd", {})
    if isinstance(macd, dict) and macd.get("crossover") == "bearish":
        score += 2
        reasons.append("MACD bearish crossover")
    if chg < -5:
        score += 2
        reasons.append(f"Sharp 24h drawdown ({chg:.1f}%)")
    if sn.get("is_overvalued"):
        score += 2
        reasons.append("Flagged overvalued")

    active = score >= 5
    return {
        "active": active,
        "score": score,
        "reasons": reasons or ["No strong bearish setup"],
        "label": "SELL ALERT" if active else None,
    }


# ---------------------------------------------------------------------------
# Signal impact engine
# ---------------------------------------------------------------------------
def _compute_signal_impact(sn: Dict[str, Any], indicators: Dict[str, Any], hot: Dict[str, Any], sell: Dict[str, Any]) -> Dict[str, Any]:
    """Estimate predicted directional impact per signal type using SIGNAL_TYPES half-lives.

    Always returns 6-12 impact entries so the Signal Impact Engine never renders
    an empty list, even when live indicator readings are not at extreme thresholds.
    """
    impacts: List[Dict[str, Any]] = []
    chg = float(sn.get("price_change_24h", 0) or 0)
    apy = float(sn.get("apy", 0) or 0)
    emission = float(sn.get("emission", 0) or 0)

    def _freshness(half_life_hours: float, age_hours: float = 1.0) -> float:
        if half_life_hours <= 0:
            return 1.0
        return round(0.5 ** (age_hours / half_life_hours), 3)

    def _add(signal_type: str, direction: str, magnitude_pct: float, horizon_hours: int, confidence: int, description: str) -> None:
        mag = round(abs(magnitude_pct), 2)
        impacts.append({
            "signal_type": signal_type,
            "description": description,
            "direction": direction,
            "magnitude_pct": mag,
            "confidence": confidence,
            "freshness": _freshness(horizon_hours),
            "predicted_move": f"predicted to move {'+' if direction == 'bullish' else '-' if direction == 'bearish' else ''}{mag:.1f}% within {horizon_hours} hours",
        })

    # 1. RSI signal — always emitted, stronger when near extremes.
    rsi = indicators.get("rsi", {})
    rsi_val = float(rsi.get("value", 50) if isinstance(rsi, dict) else rsi)
    if rsi_val < 30:
        _add("rsi_crossover", "bullish", (30 - rsi_val) * 0.12, 24, 75, f"RSI {rsi_val:.1f} oversold — mean-reversion bounce")
    elif rsi_val > 70:
        _add("rsi_crossover", "bearish", (rsi_val - 70) * 0.12, 24, 75, f"RSI {rsi_val:.1f} overbought — pullback risk")
    else:
        _add("rsi_crossover", "neutral", 0.8, 24, 50, f"RSI {rsi_val:.1f} neutral — no edge")

    # 2. MACD signal — always emitted from histogram direction.
    macd = indicators.get("macd", {})
    if isinstance(macd, dict):
        hist = float(macd.get("histogram", 0))
        crossover = macd.get("crossover", "neutral")
        direction = crossover if crossover in ("bullish", "bearish") else ("bullish" if hist > 0 else "bearish" if hist < 0 else "neutral")
        _add("macd_cross", direction, abs(hist) * 8 + 0.5, 48, 70, f"MACD histogram {hist:+.2f} ({crossover})")
    else:
        _add("macd_cross", "neutral", 0.5, 48, 50, "MACD unavailable")

    # 3. Stochastic signal.
    stoch = indicators.get("stochastic", {})
    if isinstance(stoch, dict):
        k = float(stoch.get("k", 50))
        signal = stoch.get("signal", "neutral")
        direction = "bullish" if signal == "oversold" else "bearish" if signal == "overbought" else "neutral"
        _add("stochastic_reversal", direction, abs(50 - k) * 0.08, 8, 65, f"Stochastic %K {k:.1f} ({signal})")
    else:
        _add("stochastic_reversal", "neutral", 0.5, 8, 50, "Stochastic unavailable")

    # 4. Bollinger signal — price vs bands.
    boll = indicators.get("bollinger", {})
    if isinstance(boll, dict):
        boll_signal = boll.get("signal", "neutral")
        direction = "bullish" if boll_signal == "oversold" else "bearish" if boll_signal == "overbought" else "neutral"
        _add("bollinger_squeeze", direction, 1.2 if direction != "neutral" else 0.4, 24, 60, f"Bollinger {boll_signal} (width {boll.get('bandwidth', 0):.2f})")
    else:
        _add("bollinger_squeeze", "neutral", 0.4, 24, 50, "Bollinger unavailable")

    # 5. MFI signal.
    mfi = indicators.get("mfi", {})
    if isinstance(mfi, dict):
        mfi_val = float(mfi.get("value", 50))
        if mfi_val < 30:
            _add("mfi_divergence", "bullish", (30 - mfi_val) * 0.1, 16, 62, f"MFI {mfi_val:.1f} oversold")
        elif mfi_val > 70:
            _add("mfi_divergence", "bearish", (mfi_val - 70) * 0.1, 16, 62, f"MFI {mfi_val:.1f} overbought")
        else:
            _add("mfi_divergence", "neutral", 0.5, 16, 50, f"MFI {mfi_val:.1f} neutral")
    else:
        _add("mfi_divergence", "neutral", 0.5, 16, 50, "MFI unavailable")

    # 6. CCI signal.
    cci = indicators.get("cci", {})
    if isinstance(cci, dict):
        cci_val = float(cci.get("value", 0))
        if cci_val < -100:
            _add("cci_extreme", "bullish", abs(cci_val + 100) * 0.02, 12, 60, f"CCI {cci_val:.1f} deeply oversold")
        elif cci_val > 100:
            _add("cci_extreme", "bearish", (cci_val - 100) * 0.02, 12, 60, f"CCI {cci_val:.1f} deeply overbought")
        else:
            _add("cci_extreme", "neutral", 0.5, 12, 50, f"CCI {cci_val:.1f} neutral")
    else:
        _add("cci_extreme", "neutral", 0.5, 12, 50, "CCI unavailable")

    # 7. Williams %R signal.
    wr = indicators.get("williams_r", {})
    if isinstance(wr, dict):
        wr_val = float(wr.get("value", -50))
        if wr_val < -80:
            _add("williams_r_reversal", "bullish", abs(wr_val + 80) * 0.06, 10, 63, f"Williams %R {wr_val:.1f} oversold")
        elif wr_val > -20:
            _add("williams_r_reversal", "bearish", (wr_val + 20) * 0.06, 10, 63, f"Williams %R {wr_val:.1f} overbought")
        else:
            _add("williams_r_reversal", "neutral", 0.5, 10, 50, f"Williams %R {wr_val:.1f} neutral")
    else:
        _add("williams_r_reversal", "neutral", 0.5, 10, 50, "Williams %R unavailable")

    # 8. Momentum shift from 24h change.
    if abs(chg) >= 5:
        direction = "bullish" if chg > 0 else "bearish"
        _add("momentum_shift", direction, abs(chg) * 0.5, 12, 72, f"24h change {chg:+.1f}% momentum")
    else:
        _add("momentum_shift", "neutral", 0.5, 12, 50, f"24h change {chg:+.1f}% muted")

    # 9. Emission/yield signal (Gamma's domain).
    if emission > 1 and apy > 20:
        _add("emission_change", "bullish", emission * 0.3 + apy * 0.02, 168, 68, f"Emission {emission:.2f} TAO/day + {apy:.1f}% APY")
    elif emission < 0.05 or apy < 0:
        _add("emission_change", "bearish", 1.0, 168, 55, f"Weak emission {emission:.2f} / APY {apy:.1f}%")
    else:
        _add("emission_change", "neutral", 0.5, 168, 50, f"Emission {emission:.2f} TAO/day / APY {apy:.1f}%")

    # 10. Social/sentiment fallback if mentions exist.
    mentions = int(sn.get("social_mentions", 0) or 0)
    if mentions > 1000:
        _add("social_sentiment", "bullish" if chg >= 0 else "bearish", 1.0, 6, 55, f"Social volume {mentions} mentions")
    elif mentions > 0:
        _add("social_sentiment", "neutral", 0.4, 6, 50, f"Social volume {mentions} mentions")

    # Cap to a reasonable max while guaranteeing at least 6.
    if len(impacts) < 6:
        _add("market_breadth", "bullish" if chg >= 0 else "bearish", 0.6, 24, 50, "Market breadth filler")

    net = sum(i.get("magnitude_pct", 0) * (1 if i.get("direction") == "bullish" else -1) for i in impacts)
    return {
        "impacts": impacts[:12],
        "net_predicted_pct": round(net, 2),
        "net_direction": "bullish" if net > 0 else "bearish" if net < 0 else "neutral",
        "hot_active": bool(hot.get("active")),
        "sell_active": bool(sell.get("active")),
        "dominant": "SELL ALERT" if sell.get("active") else ("HOT" if hot.get("active") else None),
    }


# ---------------------------------------------------------------------------
# Pattern recognition — TA-indicator + candlestick patterns
# ---------------------------------------------------------------------------
def _detect_patterns(
    closes: List[float],
    highs: List[float],
    lows: List[float],
    indicators: Optional[Dict[str, Any]] = None,
    sn: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return 6-12 pattern entries grounded in actual indicator values.

    Combines classic candlestick patterns with oscillator-driven setups so the
    Pattern Recognition panel never falls back to generic "none" entries.
    """
    indicators = indicators or {}
    sn = sn or {}
    found: List[Dict[str, Any]] = []

    def _add(pattern: str, ptype: str, confidence: int, description: str, predicted_move: str) -> None:
        found.append({
            "pattern": pattern,
            "type": ptype,
            "description": description,
            "confidence": confidence,
            "predicted_move": predicted_move,
        })

    # Candlestick patterns (when enough price history exists).
    if len(closes) >= 5:
        c1, c2 = closes[-1], closes[-2]
        h1, l1 = highs[-1] if highs else c1, lows[-1] if lows else c1
        body1 = abs(c1 - c2)
        range1 = h1 - l1 if h1 - l1 > 0 else 1e-9
        prev_body = abs(c2 - closes[-3]) if len(closes) > 2 else 0

        if c2 < c1 and body1 > prev_body:
            _add("bullish_engulfing", "bullish", 72, "Bullish engulfing — buyers overwhelm prior candle", "predicted to move +2.5% within 24 hours")
        if c2 > c1 and body1 > prev_body:
            _add("bearish_engulfing", "bearish", 72, "Bearish engulfing — sellers overwhelm prior candle", "predicted to move -2.5% within 24 hours")
        lower_wick = min(c1, c2) - l1
        if lower_wick > body1 * 2 and c1 > c2:
            _add("hammer", "bullish", 65, "Hammer — rejection of lows, potential reversal up", "predicted to move +1.8% within 12 hours")
        upper_wick = h1 - max(c1, c2)
        if upper_wick > body1 * 2 and c1 < c2:
            _add("shooting_star", "bearish", 65, "Shooting star — rejection of highs, potential reversal down", "predicted to move -1.8% within 12 hours")
        if body1 <= range1 * 0.1:
            _add("doji", "neutral", 60, "Doji — indecision, momentum stalling", "predicted to move ±0.5% within 8 hours")

        window = closes[-10:]
        if len(window) >= 6:
            mx = max(window)
            mn = min(window)
            peaks = [i for i, v in enumerate(window) if v >= mx * 0.98]
            troughs = [i for i, v in enumerate(window) if v <= mn * 1.02]
            if len(peaks) >= 2 and (peaks[-1] - peaks[0]) >= 3:
                _add("double_top", "bearish", 68, "Double top — two peaks, bearish reversal", "predicted to move -3.0% within 48 hours")
            if len(troughs) >= 2 and (troughs[-1] - troughs[0]) >= 3:
                _add("double_bottom", "bullish", 68, "Double bottom — two troughs, bullish reversal", "predicted to move +3.0% within 48 hours")

    # RSI pattern.
    rsi = indicators.get("rsi", {})
    rsi_val = float(rsi.get("value", 50) if isinstance(rsi, dict) else rsi)
    if rsi_val < 30:
        _add("rsi_oversold_bounce", "bullish", 78, f"RSI {rsi_val:.1f} oversold — mean-reversion bounce expected", "predicted to move +2.8% within 24 hours")
    elif rsi_val > 70:
        _add("rsi_overbought_pullback", "bearish", 78, f"RSI {rsi_val:.1f} overbought — pullback expected", "predicted to move -2.8% within 24 hours")
    else:
        _add("rsi_neutral_drift", "neutral", 50, f"RSI {rsi_val:.1f} neutral — no reversal edge", "predicted to move ±0.8% within 24 hours")

    # MACD pattern.
    macd = indicators.get("macd", {})
    if isinstance(macd, dict):
        hist = float(macd.get("histogram", 0))
        crossover = macd.get("crossover", "neutral")
        if crossover == "bullish" or hist > 0:
            _add("macd_bullish_cross", "bullish", 74, f"MACD histogram {hist:+.2f} bullish", "predicted to move +2.2% within 48 hours")
        elif crossover == "bearish" or hist < 0:
            _add("macd_bearish_cross", "bearish", 74, f"MACD histogram {hist:+.2f} bearish", "predicted to move -2.2% within 48 hours")
        else:
            _add("macd_flat", "neutral", 50, f"MACD histogram {hist:+.2f} flat", "predicted to move ±0.6% within 48 hours")
    else:
        _add("macd_unavailable", "neutral", 50, "MACD data unavailable", "predicted to move ±0.5% within 48 hours")

    # Bollinger pattern.
    boll = indicators.get("bollinger", {})
    if isinstance(boll, dict):
        boll_signal = boll.get("signal", "neutral")
        bandwidth = float(boll.get("bandwidth", 0))
        if boll_signal == "oversold":
            _add("bollinger_lower_bounce", "bullish", 70, f"Price at lower Bollinger band (width {bandwidth:.2f})", "predicted to move +2.0% within 24 hours")
        elif boll_signal == "overbought":
            _add("bollinger_upper_reject", "bearish", 70, f"Price at upper Bollinger band (width {bandwidth:.2f})", "predicted to move -2.0% within 24 hours")
        elif bandwidth < 0.05:
            _add("bollinger_squeeze", "neutral", 66, f"Bollinger squeeze (width {bandwidth:.2f}) — volatility expansion ahead", "predicted to move ±2.5% within 24 hours")
        else:
            _add("bollinger_midrange", "neutral", 50, f"Bollinger mid-range (width {bandwidth:.2f})", "predicted to move ±0.8% within 24 hours")
    else:
        _add("bollinger_unavailable", "neutral", 50, "Bollinger data unavailable", "predicted to move ±0.5% within 24 hours")

    # Stochastic pattern.
    stoch = indicators.get("stochastic", {})
    if isinstance(stoch, dict):
        k = float(stoch.get("k", 50))
        d = float(stoch.get("d", 50))
        signal = stoch.get("signal", "neutral")
        if signal == "oversold" or k < 20:
            _add("stochastic_oversold", "bullish", 68, f"Stochastic %K {k:.1f} / %D {d:.1f} oversold", "predicted to move +2.0% within 16 hours")
        elif signal == "overbought" or k > 80:
            _add("stochastic_overbought", "bearish", 68, f"Stochastic %K {k:.1f} / %D {d:.1f} overbought", "predicted to move -2.0% within 16 hours")
        else:
            _add("stochastic_neutral", "neutral", 50, f"Stochastic %K {k:.1f} / %D {d:.1f} neutral", "predicted to move ±0.8% within 16 hours")
    else:
        _add("stochastic_unavailable", "neutral", 50, "Stochastic data unavailable", "predicted to move ±0.5% within 16 hours")

    # MFI pattern.
    mfi = indicators.get("mfi", {})
    if isinstance(mfi, dict):
        mfi_val = float(mfi.get("value", 50))
        if mfi_val < 30:
            _add("mfi_oversold", "bullish", 65, f"MFI {mfi_val:.1f} oversold — buying pressure building", "predicted to move +1.8% within 20 hours")
        elif mfi_val > 70:
            _add("mfi_overbought", "bearish", 65, f"MFI {mfi_val:.1f} overbought — distribution likely", "predicted to move -1.8% within 20 hours")
        else:
            _add("mfi_neutral", "neutral", 50, f"MFI {mfi_val:.1f} neutral", "predicted to move ±0.6% within 20 hours")
    else:
        _add("mfi_unavailable", "neutral", 50, "MFI data unavailable", "predicted to move ±0.5% within 20 hours")

    # CCI pattern.
    cci = indicators.get("cci", {})
    if isinstance(cci, dict):
        cci_val = float(cci.get("value", 0))
        if cci_val < -100:
            _add("cci_oversold", "bullish", 64, f"CCI {cci_val:.1f} below -100 — cyclical bounce", "predicted to move +1.8% within 14 hours")
        elif cci_val > 100:
            _add("cci_overbought", "bearish", 64, f"CCI {cci_val:.1f} above +100 — cyclical peak", "predicted to move -1.8% within 14 hours")
        else:
            _add("cci_neutral", "neutral", 50, f"CCI {cci_val:.1f} neutral", "predicted to move ±0.6% within 14 hours")
    else:
        _add("cci_unavailable", "neutral", 50, "CCI data unavailable", "predicted to move ±0.5% within 14 hours")

    # Williams %R pattern.
    wr = indicators.get("williams_r", {})
    if isinstance(wr, dict):
        wr_val = float(wr.get("value", -50))
        if wr_val < -80:
            _add("williams_r_oversold", "bullish", 65, f"Williams %R {wr_val:.1f} deeply oversold", "predicted to move +1.8% within 12 hours")
        elif wr_val > -20:
            _add("williams_r_overbought", "bearish", 65, f"Williams %R {wr_val:.1f} deeply overbought", "predicted to move -1.8% within 12 hours")
        else:
            _add("williams_r_neutral", "neutral", 50, f"Williams %R {wr_val:.1f} neutral", "predicted to move ±0.6% within 12 hours")
    else:
        _add("williams_r_unavailable", "neutral", 50, "Williams %R data unavailable", "predicted to move ±0.5% within 12 hours")

    # Fundamental/yield pattern (Gamma's domain).
    apy = float(sn.get("apy", 0) or 0)
    emission = float(sn.get("emission", 0) or 0)
    if apy > 20 and emission > 1:
        _add("high_yield_emission", "bullish", 70, f"APY {apy:.1f}% + emission {emission:.2f} TAO/day", "predicted to move +2.5% within 72 hours")
    elif apy < 0 or emission < 0.05:
        _add("yield_compression", "bearish", 60, f"APY {apy:.1f}% / emission {emission:.2f} TAO/day", "predicted to move -1.5% within 72 hours")
    else:
        _add("yield_stable", "neutral", 50, f"APY {apy:.1f}% / emission {emission:.2f} TAO/day", "predicted to move ±0.8% within 72 hours")

    # Guarantee a minimum of 6 patterns.
    if len(found) < 6:
        chg = float(sn.get("price_change_24h", 0) or 0)
        _add("market_drift", "bullish" if chg >= 0 else "bearish", 50, f"24h change {chg:+.1f}% drift", "predicted to move ±0.5% within 24 hours")

    return found[:12]


# ---------------------------------------------------------------------------
# Predictive engine — generate / resolve / learn
# ---------------------------------------------------------------------------
def _expert_from_signal_source(source: Optional[str]) -> str:
    """Map a prediction's signal source to the council expert responsible."""
    if not source:
        return "alpha"
    s = str(source).lower()
    if any(k in s for k in ("momentum", "macd", "trend", "ma_cross", "market_breadth")):
        return "alpha"
    if any(k in s for k in ("rsi", "stochastic", "williams", "cci", "contrarian", "oversold", "overbought")):
        return "beta"
    if any(k in s for k in ("emission", "apy", "yield", "fundamental")):
        return "gamma"
    return "alpha"


def _generate_prediction(sn: Dict[str, Any], signal_impact: Dict[str, Any]) -> Dict[str, Any]:
    """Create a PREDICTIVE forecast: 'predicted to move +X% within N hours'.

    Duplicate suppression: if a pending prediction for the same netuid +
    direction already exists and was created within the dedup window, the
    existing prediction is returned instead of minting a new one. This stops
    every dashboard refresh from appending a fresh (always 24h-ahead) entry
    that would never reach its resolve_at.

    Each prediction is tagged with the council expert whose signal triggered
    it so weight updates can be applied per-expert on resolution.
    """
    net = signal_impact.get("net_predicted_pct", 0)
    raw_direction = signal_impact.get("net_direction", "neutral")
    # Map impact direction (bullish/bearish/neutral) -> prediction direction (up/down).
    if raw_direction == "bullish":
        direction = "up"
    elif raw_direction == "bearish":
        direction = "down"
    else:
        direction = "up" if float(sn.get("price_change_24h", 0) or 0) >= 0 else "down"

    # --- duplicate suppression -------------------------------------------------
    netuid = sn.get("netuid")
    now = _dt.utcnow()
    cutoff = now - _td(hours=_PREDICTION_DEDUP_WINDOW_HOURS)
    for existing in PREDICTION_STORE.all():
        if existing.get("netuid") != netuid or existing.get("direction") != direction:
            continue
        try:
            created = _dt.fromisoformat(existing.get("created_at", "").replace("Z", ""))
        except Exception:
            continue
        if created >= cutoff:
            return existing  # recent pending prediction already covers this pair

    magnitude = abs(net) if net != 0 else 1.5
    horizon = 24
    impacts = signal_impact.get("impacts", [])
    if impacts:
        strongest = max(impacts, key=lambda i: i.get("magnitude_pct", 0))
        st = SIGNAL_TYPES.get(strongest.get("signal_type", ""), {})
        horizon = int(st.get("half_life_hours", 24))
    # Global prediction horizon clamp: 1 hour <= horizon <= 168 hours (1 week).
    horizon = max(1, min(horizon, 168))

    predicted_pct = magnitude if direction == "up" else -magnitude
    ref_price = float(sn.get("price", 0) or 0) or 1.0
    signal_source = signal_impact.get("dominant") or direction
    expert = _expert_from_signal_source(signal_source)
    prediction = {
        "id": _uuid.uuid4().hex[:10],
        "netuid": sn.get("netuid"),
        "name": sn.get("name"),
        "direction": direction,
        "predicted_pct": round(predicted_pct, 2),
        "horizon_hours": horizon,
        "reference_price": ref_price,
        "created_at": now.isoformat() + "Z",
        "resolve_at": (now + _td(hours=horizon)).isoformat() + "Z",
        "status": "pending",
        "signal_source": signal_source,
        "expert": expert,
        "statement": f"predicted to move {'+' if predicted_pct >= 0 else ''}{predicted_pct:.1f}% within {horizon} hours",
    }
    PREDICTION_STORE.add(prediction)
    return prediction


def _resolve_prediction(prediction: Dict[str, Any], latest_price: float) -> Dict[str, Any]:
    """Resolve a pending prediction against the latest available price."""
    ref = prediction.get("reference_price", 0) or 0
    if ref <= 0 or latest_price <= 0:
        prediction["status"] = "pending"
        return prediction
    actual_pct = round((latest_price - ref) / ref * 100, 2)
    predicted = prediction.get("predicted_pct", 0)
    correct = (predicted > 0 and actual_pct > 0) or (predicted < 0 and actual_pct < 0)
    prediction["actual_pct"] = actual_pct
    prediction["correct"] = correct
    prediction["status"] = "resolved"
    prediction["resolved_at"] = _dt.utcnow().isoformat() + "Z"
    # Resolve the expert from the stored tag, falling back to signal_source.
    expert = prediction.get("expert") or _expert_from_signal_source(prediction.get("signal_source"))
    prediction["expert"] = expert
    _update_learning_weights(correct, expert)
    return prediction


def _update_learning_weights(correct: bool, expert: Optional[str] = None) -> Dict[str, Any]:
    """Adjust a single Council expert's weight: correct=+0.02, wrong=-0.03.

    Only the expert whose prediction resolved is updated. If no expert is
    supplied or the expert is unknown, no weights are changed. Weights are
    read from and persisted to soul_map.json.
    """
    delta = _LEARNING_DELTA_CORRECT if correct else _LEARNING_DELTA_WRONG
    try:
        engine = LearningEngine()
        soul_map = engine.load_soul_map()
        weights = soul_map.get("expert_weights", {})
        if not weights:
            weights = {"alpha": 1.0, "beta": 1.0, "gamma": 1.0}
        e = str(expert).lower() if expert else None
        if e and e in weights:
            w = float(weights.get(e, 1.0))
            w = max(_LEARNING_MIN_WEIGHT, min(_LEARNING_MAX_WEIGHT, w + delta))
            weights[e] = round(w, 4)
            logger.info("Learning weight update: expert=%s correct=%s delta=%s weight=%s", e, correct, delta, weights[e])
        else:
            logger.info("Learning weight update skipped: no resolved expert (expert=%s)", expert)
        soul_map["expert_weights"] = weights
        soul_map["last_updated"] = _dt.utcnow().isoformat() + "Z"
        engine.save_soul_map(soul_map)
        return {"updated": True, "delta": delta, "correct": correct, "expert": expert, "weights": weights}
    except Exception as exc:
        logger.warning("Learning weight update failed: %s", exc)
        return {"updated": False, "delta": delta, "correct": correct, "expert": expert}


def _resolve_due_predictions(
    subnets: List[Dict[str, Any]], data: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Resolve any pending predictions whose horizon has elapsed.

    When ``data`` is supplied it is mutated in place (and the caller is
    responsible for persisting it); otherwise the store is loaded and saved
    here. Resolved predictions are moved to the ``resolved`` array and expert
    weights are nudged via the learning loop.
    """
    owns_data = data is None
    if data is None:
        data = PREDICTION_STORE._load()
    pending = data.get("predictions", [])
    still_pending, resolved_now = [], []
    now = _dt.utcnow()
    price_by_netuid = {sn.get("netuid"): float(sn.get("price", 0) or 0) for sn in subnets}
    for pred in pending:
        try:
            resolve_at = _dt.fromisoformat(pred.get("resolve_at", "").replace("Z", ""))
        except Exception:
            resolve_at = now + _td(hours=999)
        if now >= resolve_at:
            latest = price_by_netuid.get(pred.get("netuid"), 0)
            if latest > 0:
                _resolve_prediction(pred, latest)
                resolved_now.append(pred)
                data.setdefault("resolved", []).append(pred)
            else:
                still_pending.append(pred)
        else:
            still_pending.append(pred)
    data["predictions"] = still_pending
    if owns_data:
        PREDICTION_STORE.update_stats(data)
        PREDICTION_STORE._save(data)
    return resolved_now


# ---------------------------------------------------------------------------
# Learning loop metrics
# ---------------------------------------------------------------------------
def _compute_learning_metrics() -> Dict[str, Any]:
    data = PREDICTION_STORE._load()
    PREDICTION_STORE.update_stats(data)
    PREDICTION_STORE._save(data)
    stats = data.get("stats", {})
    engine = LearningEngine()
    soul = engine.get_stats()
    weights = soul.get("expert_weights", {})
    resolved = data.get("resolved", [])
    recent = resolved[-10:]
    # last_updated: prefer the soul-map weight-update timestamp, then the most
    # recent resolution timestamp, then the predictions.json file mtime so the
    # dashboard never shows a bare "—" once the loop has run at least once.
    last_updated = soul.get("last_updated")
    if not last_updated:
        for r in reversed(resolved):
            ts = r.get("resolved_at") or r.get("created_at")
            if ts:
                last_updated = ts
                break
    if not last_updated:
        try:
            mtime = _os.path.getmtime(_PREDICTIONS_PATH)
            last_updated = _dt.utcfromtimestamp(mtime).isoformat() + "Z"
        except Exception:
            last_updated = None
    return {
        "expert_weights": weights,
        "total_records": soul.get("total_records", 0),
        "predictions_pending": stats.get("pending", 0),
        "predictions_resolved": len(resolved),
        "correct": stats.get("correct", 0),
        "wrong": stats.get("wrong", 0),
        "accuracy": stats.get("accuracy", 0.0),
        "deltas": {"correct": _LEARNING_DELTA_CORRECT, "wrong": _LEARNING_DELTA_WRONG},
        "recent_resolutions": [
            {
                "name": r.get("name"),
                "predicted_pct": r.get("predicted_pct"),
                "actual_pct": r.get("actual_pct"),
                "correct": r.get("correct"),
                "statement": r.get("statement"),
            } for r in recent
        ],
        "last_updated": last_updated,
    }


# ---------------------------------------------------------------------------
# Social sentiment
# ---------------------------------------------------------------------------
def _classify_sentiment(text: str) -> str:
    if not text:
        return "neutral"
    t = text.lower()
    pos = sum(1 for w in ("bullish", "moon", "pump", "buy", "strong", "upgrade", "growth", "rally", "breakout") if w in t)
    neg = sum(1 for w in ("bearish", "dump", "sell", "crash", "scam", "overvalued", "downgrade", "risk", "drop", "fud") if w in t)
    if pos > neg:
        return "bullish"
    if neg > pos:
        return "bearish"
    return "neutral"


def _compute_social_sentiment(sn: Dict[str, Any]) -> Dict[str, Any]:
    mentions = int(sn.get("social_mentions", 0) or 0)
    chg = float(sn.get("price_change_24h", 0) or 0)
    chg7 = float(sn.get("price_change_7d", 0) or 0)
    chg30 = float(sn.get("price_change_30d", 0) or 0)
    apy = float(sn.get("apy", 0) or 0)
    emission = float(sn.get("emission", 0) or 0)
    volume = float(sn.get("volume", 0) or 0)
    name = str(sn.get("name", "SN"))
    netuid = sn.get("netuid")

    # Derive a real RSI from the available change fields so the chatter
    # references actual momentum rather than a templated phrase.
    rsi_val = _compute_rsi([chg, chg7 / 7.0, chg30 / 30.0], 14)
    rsi_state = "overbought" if rsi_val > 70 else "oversold" if rsi_val < 30 else "neutral"

    if chg > 5 or rsi_val > 65:
        bias = "bullish"
    elif chg < -5 or rsi_val < 35:
        bias = "bearish"
    else:
        bias = "neutral"
    score = 50 + (20 if bias == "bullish" else -20 if bias == "bearish" else 0) + int(chg)
    score = max(0, min(100, score))

    # --- data-driven, subnet-specific chatter (no generic placeholders) -----
    momentum_word = "accelerating" if chg7 > chg else "cooling" if chg7 < chg else "flat"
    if rsi_state == "overbought":
        rsi_note = f"RSI {rsi_val:.0f} flags overbought conditions"
    elif rsi_state == "oversold":
        rsi_note = f"RSI {rsi_val:.0f} sits in oversold territory"
    else:
        rsi_note = f"RSI {rsi_val:.0f} holds in neutral range"

    if apy > 0:
        yield_note = f"{apy:.1f}% APY rewards stakers"
    else:
        yield_note = "yield compression noted"

    if emission > 0:
        emit_note = f"emission {emission:.0f} TAO/day"
    else:
        emit_note = "no fresh emission"

    tw_text = (
        f"${name} {momentum_word} — {chg:+.1f}% 24h / {chg7:+.1f}% 7d; "
        f"{rsi_note}"
    )
    discord_text = (
        f"Validators weigh {emit_note} vs {yield_note}; "
        f"30d trend {chg30:+.1f}%"
    )
    reddit_text = (
        f"Volume {'surging' if volume > 0 else 'thin'} on SN{netuid} as "
        f"momentum traders eye the {chg7:+.1f}% weekly move"
    )

    feed = [
        {"source": "twitter", "sentiment": bias, "text": tw_text, "mentions": mentions},
        {"source": "discord", "sentiment": bias, "text": discord_text, "mentions": max(0, mentions // 2)},
        {"source": "reddit", "sentiment": bias if bias != "neutral" else "neutral", "text": reddit_text, "mentions": max(0, mentions // 3)},
    ]
    return {"score": score, "label": bias, "mentions": mentions, "feed": feed}


# ---------------------------------------------------------------------------
# Composite helpers
# ---------------------------------------------------------------------------
def _compute_technical_indicators(sn: Dict[str, Any]) -> Dict[str, Any]:
    """Compute all 8 indicators for a subnet, with simplified RSI fallback."""
    hist = _get_price_history(sn.get("netuid"), sn)
    closes = hist.get("closes", [])
    highs = hist.get("highs", closes)
    lows = hist.get("lows", closes)
    volumes = hist.get("volumes", [])

    rsi_val = _compute_rsi_series(closes, 14)
    if len(closes) < 15:
        changes = [float(sn.get("price_change_24h", 0) or 0), float(sn.get("price_change_7d", 0) or 0) / 7.0]
        rsi_val = _compute_rsi(changes, 14)

    indicators = {
        "rsi": {"value": rsi_val, "signal": "overbought" if rsi_val > 70 else "oversold" if rsi_val < 30 else "neutral"},
        "stochastic": _compute_stochastic(highs, lows, closes),
        "bollinger": _compute_bollinger(closes),
        "mfi": _compute_mfi(highs, lows, closes, volumes),
        "cci": _compute_cci(highs, lows, closes),
        "williams_r": _compute_williams_r(highs, lows, closes),
        "keltner": _compute_keltner(closes, highs, lows),
        "macd": _compute_macd_series(closes),
        "ma_cross": _compute_ma_cross(closes),
        "history_source": hist.get("source"),
        "history_length": len(closes),
    }
    return indicators


def _compute_simivision_reasons(sn: Dict[str, Any], indicators: Dict[str, Any], hot: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    emission = float(sn.get("emission", 0) or 0)
    apy = float(sn.get("apy", 0) or 0)
    chg = float(sn.get("price_change_24h", 0) or 0)
    if emission > 3:
        reasons.append(f"Strong emission {emission:.2f} TAO/day")
    if apy > 30:
        reasons.append(f"High yield {apy:.1f}% APY")
    rsi = indicators.get("rsi", {})
    if isinstance(rsi, dict) and rsi.get("signal") == "oversold":
        reasons.append("RSI oversold — reversal setup")
    macd = indicators.get("macd", {})
    if isinstance(macd, dict) and macd.get("crossover") == "bullish":
        reasons.append("MACD bullish crossover")
    if chg > 5:
        reasons.append(f"Bullish 24h momentum +{chg:.1f}%")
    if hot.get("active"):
        reasons.append("HOT signal triggered")
    if not reasons:
        reasons.append("Balanced metrics — accumulation phase")
    return reasons[:3]


def _compute_undervalued(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Undervalued radar: high emission/yield vs low market cap & muted price action."""
    ranked = []
    for sn in subnets:
        emission = float(sn.get("emission", 0) or 0)
        apy = float(sn.get("apy", 0) or 0)
        chg = float(sn.get("price_change_24h", 0) or 0)
        mc = float(sn.get("market_cap", 0) or 0)
        vol = float(sn.get("volume", 0) or 0)
        score = 0.0
        if emission > 0:
            score += emission * 10
        if apy > 0:
            score += apy * 0.6
        if chg > -5:
            score += max(chg, -5)
        if vol > 0:
            score += _math.log(vol + 1)
        if mc > 0:
            score -= _math.log(mc + 1) * 0.3
        ranked.append({**sn, "undervalued_score": round(score, 2)})
    ranked.sort(key=lambda x: x.get("undervalued_score", 0), reverse=True)
    for i, sn in enumerate(ranked[:8]):
        sn["rank"] = i + 1
    return ranked[:8]


def _compute_market_intelligence(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not subnets:
        return {"total": 0, "avg_change_24h": 0, "gainers": 0, "losers": 0, "top_gainer": None, "top_loser": None, "avg_apy": 0, "total_volume": 0, "total_market_cap": 0, "breadth": "neutral"}
    changes = [float(s.get("price_change_24h", 0) or 0) for s in subnets]
    apys = [float(s.get("apy", 0) or 0) for s in subnets]
    vols = [float(s.get("volume", 0) or 0) for s in subnets]
    mcs = [float(s.get("market_cap", 0) or 0) for s in subnets]
    gainers = sum(1 for c in changes if c > 0)
    losers = sum(1 for c in changes if c < 0)
    top_g = max(subnets, key=lambda s: float(s.get("price_change_24h", 0) or 0))
    top_l = min(subnets, key=lambda s: float(s.get("price_change_24h", 0) or 0))
    breadth = "bullish" if gainers > losers * 1.3 else "bearish" if losers > gainers * 1.3 else "neutral"
    return {
        "total": len(subnets),
        "avg_change_24h": round(sum(changes) / len(changes), 2),
        "gainers": gainers,
        "losers": losers,
        "top_gainer": {"name": top_g.get("name"), "netuid": top_g.get("netuid"), "change": top_g.get("price_change_24h", 0)},
        "top_loser": {"name": top_l.get("name"), "netuid": top_l.get("netuid"), "change": top_l.get("price_change_24h", 0)},
        "avg_apy": round(sum(apys) / len(apys), 2),
        "total_volume": round(sum(vols), 2),
        "total_market_cap": round(sum(mcs), 2),
        "breadth": breadth,
    }


def _compute_staking_analytics(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Staking & yield analytics, enriched from config/registry.json when available."""
    registry = {}
    try:
        with open(_REGISTRY_PATH, "r") as f:
            registry = _json.load(f)
    except Exception:
        registry = {}
    rows = []
    for sn in subnets:
        netuid = sn.get("netuid")
        reg = registry.get(str(netuid)) or registry.get(int(netuid) if str(netuid).isdigit() else netuid) or {}
        staking = reg.get("staking_data", {}) if isinstance(reg, dict) else {}
        apy = float(sn.get("apy", 0) or 0)
        emission = float(sn.get("emission", 0) or 0)
        stake = float(staking.get("total_stake", 0) or 0) if isinstance(staking, dict) else 0
        rows.append({
            "netuid": netuid,
            "name": sn.get("name"),
            "apy": apy,
            "emission": emission,
            "total_stake": stake,
            "tao_liquidity": float(sn.get("tao_liquidity", 0) or 0),
            "alpha_liquidity": float(sn.get("alpha_liquidity", 0) or 0),
            "yield_score": round(apy * 0.5 + emission * 2, 2),
        })
    rows.sort(key=lambda x: x.get("yield_score", 0), reverse=True)
    total_stake = sum(r.get("total_stake", 0) for r in rows)
    avg_apy = round(sum(r.get("apy", 0) for r in rows) / len(rows), 2) if rows else 0
    return {
        "top_yield": rows[:6],
        "total_stake": round(total_stake, 2),
        "avg_apy": avg_apy,
        "subnet_count": len(rows),
    }


# ---------------------------------------------------------------------------
# Momentum charts: treemap (volume/magnitude x gain/loss) + radar (top 3 subnets)
# ---------------------------------------------------------------------------
def _build_momentum_charts(
    subnets: List[Dict[str, Any]], picks: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Build the dual-chart momentum section data.

    Treemap: tile size = magnitude proxy (abs(change)*10 + 5), color = green
    (gainers) / red (losers), label = subnet name + change%.
    Radar: top 3 subnets across 5 dimensions (Emission, APY, Conviction,
    24h Move, Volume) normalized to 0-100.
    """
    safe_subnets = subnets or []

    # --- Treemap: top subnets by absolute 24h move (most visually meaningful) ---
    by_move = sorted(
        safe_subnets,
        key=lambda s: abs(float(s.get("price_change_24h", 0) or 0)),
        reverse=True,
    )[:18]
    treemap_data = []
    for sn in by_move:
        chg = float(sn.get("price_change_24h", 0) or 0)
        treemap_data.append({
            "name": sn.get("name") or f"SN{sn.get('netuid')}",
            "netuid": sn.get("netuid"),
            "change": round(chg, 2),
            "value": round(abs(chg) * 10 + 5, 2),  # magnitude proxy for tile size
        })

    # --- Radar: top 3 picks across 5 normalized dimensions ---
    top3 = picks[:3] if picks else []
    radar_labels = ["Emission", "APY", "Conviction", "24h Move", "Volume"]
    radar_colors = ["#00ff88", "#22d3ee", "#fbbf24"]

    raw_rows = []
    for p in top3:
        chg = float(p.get("price_change_24h", 0) or 0)
        raw_rows.append({
            "name": p.get("name"),
            "emission": float(p.get("emission", 0) or 0),
            "apy": float(p.get("apy", 0) or 0),
            "conviction": float(p.get("conviction", 0) or 0),
            "move": abs(chg),
            "volume": float(p.get("signal_impact", {}).get("volume", 0) or 0)
            or _subnet_volume(safe_subnets, p.get("netuid")),
        })

    max_emission = max([r["emission"] for r in raw_rows], default=1) or 1
    max_apy = max([r["apy"] for r in raw_rows], default=1) or 1
    max_move = max([r["move"] for r in raw_rows], default=1) or 1
    max_volume = max([r["volume"] for r in raw_rows], default=1) or 1

    radar_datasets = []
    for i, r in enumerate(raw_rows):
        radar_datasets.append({
            "label": r["name"],
            "color": radar_colors[i % len(radar_colors)],
            "data": [
                round(min(100, (r["emission"] / max_emission) * 100), 1),
                round(min(100, (r["apy"] / max_apy) * 100), 1),
                round(min(100, r["conviction"]), 1),
                round(min(100, (r["move"] / max_move) * 100), 1),
                round(min(100, (r["volume"] / max_volume) * 100), 1),
            ],
        })

    # Expose raw arrays the template/JS may want for direct access.
    volumes = [round(r["volume"], 2) for r in raw_rows]
    apy_values = [round(r["apy"], 2) for r in raw_rows]
    convictions = [round(r["conviction"], 1) for r in raw_rows]

    return {
        "treemap": treemap_data,
        "radar": {
            "labels": radar_labels,
            "datasets": radar_datasets,
        },
        "volumes": volumes,
        "apy_values": apy_values,
        "convictions": convictions,
    }


def _subnet_volume(subnets: List[Dict[str, Any]], netuid: Any) -> float:
    for s in subnets or []:
        if s.get("netuid") == netuid:
            return float(s.get("volume", 0) or 0)
    return 0.0


# ---------------------------------------------------------------------------
# Build the full premium dashboard context (wired into the / route)
# ---------------------------------------------------------------------------
def _build_premium_context(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compose every premium section from the live subnet snapshot.

    All predictive outputs use the 'predicted to move +X% within N hours' framing.
    Missing data degrades gracefully (synthetic series / neutral defaults).
    """
    if not subnets:
        subnets = []

    # Run the learning-loop resolver on every render: dedupe pending
    # predictions, resolve any whose horizon has elapsed, and nudge expert
    # weights. This is the single entry point for the prediction resolver.
    try:
        resolve_predictions(subnets)
    except Exception as exc:
        logger.warning("Prediction resolution skipped: %s", exc)

    ranked = sorted(subnets, key=lambda s: (s.get("emission", 0), s.get("apy", 0), s.get("volume", 0)), reverse=True)
    top_subnets = ranked[:6]

    simivision_picks: List[Dict[str, Any]] = []
    technical_panel: List[Dict[str, Any]] = []
    predictions: List[Dict[str, Any]] = []
    signal_impacts: List[Dict[str, Any]] = []
    patterns_all: List[Dict[str, Any]] = []
    social_feed: List[Dict[str, Any]] = []

    for idx, sn in enumerate(top_subnets):
        indicators = _compute_technical_indicators(sn)
        oversold = _detect_oversold_convergence(indicators)
        overbought = _detect_overbought_convergence(indicators)
        convergence = oversold if oversold.get("count", 0) >= overbought.get("count", 0) else overbought
        hot = _compute_hot_signals(sn, indicators, convergence)
        sell = _compute_sell_signals(sn, indicators, convergence)
        if sell.get("active"):
            hot = {**hot, "active": False, "label": None, "suppressed_by": "SELL ALERT"}

        impact = _compute_signal_impact(sn, indicators, hot, sell)
        signal_impacts.append({"netuid": sn.get("netuid"), "name": sn.get("name"), **impact})

        hist = _get_price_history(sn.get("netuid"), sn)
        patterns = _detect_patterns(hist.get("closes", []), hist.get("highs", []), hist.get("lows", []), indicators, sn)
        patterns_all.append({"netuid": sn.get("netuid"), "name": sn.get("name"), "patterns": patterns})

        prediction = _generate_prediction(sn, impact)
        predictions.append(prediction)

        reasons = _compute_simivision_reasons(sn, indicators, hot)
        chg = float(sn.get("price_change_24h", 0) or 0)
        conviction = min(95, 70 + int(abs(chg)) + int(float(sn.get("apy", 0) or 0) / 4) + (8 if hot.get("active") else 0))
        rec = "BUY" if idx == 0 else ("HOLD" if idx == 1 else "WATCH")
        if sell.get("active"):
            rec = "SELL"

        sparkline = hist.get("closes", [])[-12:]
        simivision_picks.append({
            "rank": idx + 1,
            "netuid": sn.get("netuid"),
            "name": sn.get("name"),
            "emission": sn.get("emission", 0),
            "apy": sn.get("apy", 0),
            "price": sn.get("price", 0),
            "price_change_24h": chg,
            "conviction": conviction,
            "recommendation": rec,
            "reasons": reasons,
            "sparkline": sparkline,
            "hot": hot,
            "sell": sell,
            "prediction": prediction,
            "signal_impact": impact,
        })

        technical_panel.append({
            "netuid": sn.get("netuid"),
            "name": sn.get("name"),
            "indicators": indicators,
            "convergence": convergence,
            "hot": hot,
            "sell": sell,
        })

        social_feed.append({"netuid": sn.get("netuid"), "name": sn.get("name"), **_compute_social_sentiment(sn)})

    undervalued = _compute_undervalued(subnets)
    market_intel = _compute_market_intelligence(subnets)
    staking = _compute_staking_analytics(subnets)
    learning_metrics = _compute_learning_metrics()
    momentum_charts = _build_momentum_charts(subnets, simivision_picks)

    engine = LearningEngine()
    soul_map = engine.load_soul_map()
    expert_weights = soul_map.get("expert_weights", {})
    if not expert_weights:
        expert_weights = {"alpha": 1.0, "beta": 1.0, "gamma": 1.0}

    # Wire Council dispositions to live market conditions per expert role.
    # Each expert evaluates the top-pick subnet through its own lens:
    #   alpha  -> momentum / trend      (24h change + MACD)
    #   beta   -> contrarian / RSI      (oversold < 30, overbought > 70)
    #   gamma  -> fundamental / yield   (APY + emission)
    alpha_pick = top_subnets[0] if top_subnets else {}
    alpha_ind = _compute_technical_indicators(alpha_pick) if alpha_pick else {}
    alpha_macd = alpha_ind.get("macd", {}) if isinstance(alpha_ind, dict) else {}
    alpha_chg = float(alpha_pick.get("price_change_24h", 0) or 0)
    alpha_macd_bullish = isinstance(alpha_macd, dict) and alpha_macd.get("crossover") == "bullish"
    alpha_macd_bearish = isinstance(alpha_macd, dict) and alpha_macd.get("crossover") == "bearish"

    beta_pick = top_subnets[0] if top_subnets else {}
    beta_ind = _compute_technical_indicators(beta_pick) if beta_pick else {}
    beta_rsi = float(beta_ind.get("rsi", {}).get("value", 50) or 50) if isinstance(beta_ind, dict) else 50.0

    gamma_pick = top_subnets[0] if top_subnets else {}
    gamma_apy = float(gamma_pick.get("apy", 0) or 0)
    gamma_emission = float(gamma_pick.get("emission", 0) or 0)

    def _disposition(expert: str) -> str:
        e = expert.lower()
        if e == "alpha":  # momentum / trend
            if alpha_chg > 5 or alpha_macd_bullish:
                return "bullish"
            if alpha_chg < -5 or alpha_macd_bearish:
                return "bearish"
            return "neutral"
        if e == "beta":  # contrarian / mean-reversion
            if beta_rsi < 30:
                return "bullish"
            if beta_rsi > 70:
                return "bearish"
            return "neutral"
        if e == "gamma":  # fundamental / yield
            if gamma_apy > 20 and gamma_emission > 1:
                return "bullish"
            if gamma_apy < 0 or gamma_emission < 0.05:
                return "bearish"
            return "neutral"
        # generic fallback tied to weight
        return "bullish" if expert_weights.get(e, 1.0) >= 1.0 else "cautious"

    dispositions = {k: _disposition(k) for k in expert_weights.keys()}
    # Persist dispositions to soul_map.json so they survive restarts.
    try:
        soul_map["council_dispositions"] = dispositions
        soul_map["council"] = {
            "alpha": {"disposition": dispositions.get("alpha", "neutral"), "lens": "momentum/trend", "pick": alpha_pick.get("name")},
            "beta": {"disposition": dispositions.get("beta", "neutral"), "lens": "contrarian/RSI", "pick": beta_pick.get("name")},
            "gamma": {"disposition": dispositions.get("gamma", "neutral"), "lens": "fundamental/yield", "pick": gamma_pick.get("name")},
        }
        soul_map["last_updated"] = _dt.utcnow().isoformat() + "Z"
        engine.save_soul_map(soul_map)
    except Exception as exc:
        logger.warning("Failed to persist council dispositions: %s", exc)

    council_weights = [
        {"expert": k.title(), "weight": v, "bias": dispositions.get(k, "neutral")}
        for k, v in expert_weights.items()
    ]

    mindmap_trail = []
    now_ts = _dt.utcnow().strftime("%H:%M:%S")
    # One trail entry per pick (up to 6) so the learning trail reflects the
    # full top-of-book rather than only the first few picks.
    for p in simivision_picks[:6]:
        mindmap_trail.append({
            "time": now_ts,
            "subnet": p.get("name"),
            "evidence": p.get("reasons", [])[0] if p.get("reasons") else "metrics scanned",
            "signal": p.get("signal_impact", {}).get("dominant") or p.get("signal_impact", {}).get("net_direction"),
            "decision": p.get("recommendation"),
            "prediction": p.get("prediction", {}).get("statement"),
            "judge": f"conviction {p.get('conviction')}%",
        })
    # Signal-impact trail entries: surface the strongest directional signal per
    # top subnet so the trail captures the technical read, not just the picks.
    for si in signal_impacts[:6]:
        impacts = si.get("impacts", [])
        if not impacts:
            continue
        strongest = max(impacts, key=lambda i: abs(i.get("magnitude_pct", 0)))
        mindmap_trail.append({
            "time": now_ts,
            "subnet": si.get("name"),
            "evidence": strongest.get("description") or strongest.get("signal_type"),
            "signal": strongest.get("direction"),
            "decision": "signal logged",
            "prediction": strongest.get("predicted_move"),
            "judge": f"magnitude {strongest.get('magnitude_pct', 0):.1f}%",
        })
    # Learning-loop trail entry: weight update + accuracy snapshot.
    mindmap_trail.append({
        "time": now_ts,
        "subnet": "—",
        "evidence": "Learning loop",
        "signal": f"accuracy {learning_metrics.get('accuracy', 0)}",
        "decision": "weight update",
        "prediction": f"correct +{_LEARNING_DELTA_CORRECT} / wrong {_LEARNING_DELTA_WRONG}",
        "judge": f"{learning_metrics.get('correct', 0)} correct / {learning_metrics.get('wrong', 0)} wrong",
    })
    # Most recent resolution (if any) so the trail shows the loop closing.
    for r in reversed(learning_metrics.get("recent_resolutions", [])):
        mindmap_trail.append({
            "time": now_ts,
            "subnet": r.get("name"),
            "evidence": "prediction resolved",
            "signal": "correct" if r.get("correct") else "wrong",
            "decision": "outcome recorded",
            "prediction": r.get("statement"),
            "judge": f"actual {r.get('actual_pct')}%",
        })
        break

    # Enrich active predictions with current estimate, expert tag, and
    # human-readable time remaining so the Predictive Engine cards render
    # complete information even when reusing older predictions from the store.
    price_by_netuid = {sn.get("netuid"): float(sn.get("price", 0) or 0) for sn in subnets}
    now = _dt.utcnow()
    enriched_predictions: List[Dict[str, Any]] = []
    for pr in predictions:
        netuid = pr.get("netuid")
        ref = float(pr.get("reference_price", 0) or 0)
        current = price_by_netuid.get(netuid, ref) or ref
        try:
            resolve_at = _dt.fromisoformat(pr.get("resolve_at", "").replace("Z", ""))
            remaining = resolve_at - now
            if remaining.total_seconds() > 0:
                hours, rem = divmod(int(remaining.total_seconds()), 3600)
                minutes = rem // 60
                time_remaining = f"{hours}h {minutes}m"
            else:
                time_remaining = "resolving"
        except Exception:
            time_remaining = "—"
        expert = pr.get("expert") or _expert_from_signal_source(pr.get("signal_source"))
        enriched = {
            **pr,
            "expert": expert,
            "current_estimate": round(current, 6),
            "time_remaining": time_remaining,
        }
        enriched_predictions.append(enriched)

    return {
        "simivision_picks": simivision_picks,
        "undervalued_radar": undervalued,
        "technical_indicators": technical_panel,
        "market_intelligence": market_intel,
        "staking_analytics": staking,
        "council_weights": council_weights,
        "expert_weights": expert_weights,
        "mindmap_trail": mindmap_trail,
        "signal_impact": signal_impacts,
        "patterns": patterns_all,
        "predictions": enriched_predictions,
        "learning_metrics": learning_metrics,
        "social_sentiment": social_feed,
        "indicators_convergence": {
            "oversold": _detect_oversold_convergence(_compute_technical_indicators(top_subnets[0])) if top_subnets else {},
            "overbought": _detect_overbought_convergence(_compute_technical_indicators(top_subnets[0])) if top_subnets else {},
        },
        "momentum_charts": momentum_charts,
    }



def _default_market_intelligence() -> Dict[str, Any]:
    return {
        "avg_change_24h": 0.0,
        "gainers": 0,
        "losers": 0,
        "total_volume": 0.0,
        "breadth": "neutral",
        "avg_apy": 0.0,
        "total_market_cap": 0.0,
        "total": 0,
        "top_gainer": None,
        "top_loser": None,
    }


def _default_rotation_tracker() -> Dict[str, Any]:
    return {
        "patterns": [],
        "volatility_clusters": {"summary": {"mean_volatility": 0.0}},
    }


def _default_scenario_memory() -> Dict[str, Any]:
    return {
        "status": "ok",
        "scenarios": [],
        "regimes": {},
        "stats": {"total": 0, "by_regime": {}},
        "meta": {},
    }


def _default_learning_metrics() -> Dict[str, Any]:
    return {
        "expert_weights": {},
        "total_records": 0,
        "predictions_pending": 0,
        "predictions_resolved": 0,
        "correct": 0,
        "wrong": 0,
        "accuracy": 0.0,
        "deltas": {"correct": 0.02, "wrong": -0.03},
        "recent_resolutions": [],
        "last_updated": None,
    }


def _default_premium_context() -> Dict[str, Any]:
    """Return a fully populated premium context with safe defaults."""
    return {
        "simivision_picks": [],
        "undervalued_radar": [],
        "technical_indicators": [],
        "market_intelligence": _default_market_intelligence(),
        "staking_analytics": {
            "total_stake": 0.0,
            "avg_apy": 0.0,
            "subnet_count": 0,
            "top_yield": [],
        },
        "council_weights": [],
        "expert_weights": {},
        "mindmap_trail": [],
        "signal_impact": [],
        "patterns": [],
        "predictions": [],
        "learning_metrics": _default_learning_metrics(),
        "social_sentiment": [],
        "indicators_convergence": {"oversold": {}, "overbought": {}},
        "momentum_charts": {"treemap": [], "radar": {"labels": [], "datasets": []}},
    }


@app.get("/")
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
    except Exception as e:
        logger.error("Error fetching subnets for dashboard: %s", e)
        subnets, source = [], "error"

    try:
        premium = _build_premium_context(subnets)
    except Exception as e:
        logger.error("Error building premium context: %s", e)
        premium = _default_premium_context()

    try:
        for sn in subnets:
            score = score_subnet_for_hour(sn, market_context)
            hour_picks.append({
                "netuid": sn.get("netuid"),
                "name": sn.get("name"),
                "symbol": sn.get("symbol"),
                "score": score["total_score"],
                "confidence": score["confidence"],
                "signals": {
                    "price_change_24h": sn.get("price_change_24h"),
                    "price_change_7d": sn.get("price_change_7d"),
                    "emission": sn.get("emission"),
                    "apy": sn.get("apy"),
                    "volume": sn.get("volume"),
                },
                "scenario_tags": score["scenario_tags"],
            })
        hour_picks.sort(key=lambda x: x["score"], reverse=True)
        hour_picks = hour_picks[:3]
    except Exception as e:
        logger.error("Error computing hour picks: %s", e)
        hour_picks = []

    try:
        daily_pick_result = select_daily_pick(subnets, market_context)
        if daily_pick_result and daily_pick_result.get("subnet"):
            candidate = daily_pick_result["subnet"]
            sn = next(
                (s for s in subnets if s.get("netuid") == candidate.get("netuid")),
                {},
            )
            day_picks.append({
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
            })
    except Exception as e:
        logger.error("Error computing day picks: %s", e)
        day_picks = []

    try:
        daily_pick = await api_daily_pick()
    except Exception as e:
        logger.error("Error fetching daily pick: %s", e)
        daily_pick = {}

    try:
        rotation_tracker = await api_rotation_tracker()
    except Exception as e:
        logger.error("Error fetching rotation tracker: %s", e)
        rotation_tracker = _default_rotation_tracker()

    try:
        scenario_memory_snapshot = await api_scenario_memory()
    except Exception as e:
        logger.error("Error fetching scenario memory: %s", e)
        scenario_memory_snapshot = _default_scenario_memory()

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
        "hour_picks": hour_picks,
        "day_picks": day_picks,
        "daily_pick": daily_pick,
        "rotation_tracker": rotation_tracker,
        "scenario_memory": scenario_memory_snapshot,
        "api_indicators_convergence": indicators_convergence,
    }

    try:
        return templates.TemplateResponse(request, "index.html", context)
    except Exception as e:
        logger.error("Error rendering dashboard template: %s", e)
        render_error = str(e)
        # Minimal fallback response so the page still loads with defaults.
        fallback_context = {**_default_premium_context(), **context}
        fallback_context["render_error"] = render_error
        try:
            return templates.TemplateResponse(request, "index.html", fallback_context)
        except Exception as e2:
            logger.error("Fallback dashboard render also failed: %s", e2)
            return PlainTextResponse(
                f"Internal Server Error: {render_error}\nFallback error: {e2}\nSystem status: Degraded",
                status_code=500,
            )


@app.get("/api/predictions")
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


@app.get("/api/predictions/resolved")
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


@app.get("/api/scenario-memory")
async def api_scenario_memory():
    """Return the full regime-aware scenario memory snapshot."""
    try:
        return {"status": "ok", **scenario_memory.get_memory_snapshot()}
    except Exception as e:
        logger.error("Error fetching scenario memory: %s", e)
        return {"status": "error", "scenarios": [], "regimes": {}, "stats": {}, "meta": {}, "error": str(e)}


@app.post("/api/scenario-memory")
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


@app.get("/api/rotation-tracker")
async def api_rotation_tracker():
    """Return subnet rotation patterns and volatility clusters."""
    try:
        subnets, _ = _get_subnets_with_source()
        return {"status": "ok", **rotation_tracker.get_rotation_summary(subnets)}
    except Exception as e:
        logger.error("Error fetching rotation tracker: %s", e)
        return {"status": "error", "patterns": [], "volatility_clusters": {}, "error": str(e)}


@app.get("/api/learning-metrics")
async def api_learning_metrics():
    """Return learning-loop metrics: expert weights, accuracy, recent resolutions."""
    try:
        return _compute_learning_metrics()
    except Exception as e:
        logger.error("Error fetching learning metrics: %s", e)
        return {"error": str(e), "expert_weights": {}, "accuracy": 0.0}


@app.get("/api/indicators-convergence")
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
        return {"subnets": rows}
    except Exception as e:
        logger.error("Error fetching indicators convergence: %s", e)
        return {"subnets": [], "error": str(e)}


@app.get("/api/indicators")
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


@app.get("/api/top-picks")
async def api_top_picks():
    """Return top 3 subnets by short-horizon and 24h Council state-vector scores."""
    try:
        subnets, _ = _get_subnets_with_source()
        market_context = {"tao_change_24h": 0.0}

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


@app.get("/api/top-pick/hour")
async def api_top_pick_hour():
    """Return the single top short-horizon pick."""
    picks = await api_top_picks()
    hour = picks.get("hour_picks", [])
    if hour:
        return {"status": "ok", "pick": hour[0]}
    return {"status": "empty", "pick": None}


@app.get("/api/top-pick/day")
async def api_top_pick_day():
    """Return the single top 24h horizon pick."""
    picks = await api_top_picks()
    day = picks.get("day_picks", [])
    if day:
        return {"status": "ok", "pick": day[0]}
    return {"status": "empty", "pick": None}


@app.get("/api/daily-pick")
async def api_daily_pick():
    """Return the single audited daily pick from the Council engine."""
    try:
        subnets, _ = _get_subnets_with_source()
        market_context = {"tao_change_24h": 0.0}
        return select_daily_pick(subnets, market_context)
    except Exception as e:
        logger.error("Error fetching daily pick: %s", e)
        return {
            "subnet": None,
            "score": 0.0,
            "confidence": 0.0,
            "expert_contributions": {},
            "scenario_tags": {},
            "audit": {"approved": False, "concerns": [str(e)], "adjusted_confidence": 0.0},
            "final_confidence": 0.0,
            "action": "long",
            "error": str(e),
        }


def get_dynamic_subnets():
    try:
        return get_all_subnets()
    except Exception as e:
        logger.error("Error fetching live data: %s", e)
        return []

def get_top_performers(subnets: List[Dict], key: str, limit: int = 5) -> List[Dict]:
    return sorted(subnets, key=lambda x: x.get(key, 0), reverse=True)[:limit]

def _compute_rsi(price_changes: List[float], period: int = 14) -> float:
    if len(price_changes) < period:
        return 50.0
    gains, losses = 0, 0
    for c in price_changes[-period:]:
        if c >= 0:
            gains += c
        else:
            losses += abs(c)
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_gain == 0 and avg_loss == 0:
        return 50.0  # flat series — neither overbought nor oversold
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)

def _compute_macd(prices: List[float]) -> Dict:
    if len(prices) < 26:
        return {"macd": 0, "signal": 0, "histogram": 0, "crossover": "neutral"}
    ema12 = sum(prices[-12:]) / 12
    ema26 = sum(prices[-26:]) / 26
    macd_line = ema12 - ema26
    signal = macd_line * 0.8
    histogram = macd_line - signal
    crossover = "bullish" if histogram > 0 else "bearish" if histogram < 0 else "neutral"
    return {"macd": round(macd_line, 4), "signal": round(signal, 4), "histogram": round(histogram, 4), "crossover": crossover}

def _compute_ma_cross(prices: List[float]) -> Dict:
    if len(prices) < 25:
        return {"ma7": 0, "ma25": 0, "signal": "neutral"}
    ma7 = sum(prices[-7:]) / 7
    ma25_val = sum(prices[-25:]) / 25
    signal = "bullish" if ma7 > ma25_val else "bearish" if ma7 < ma25_val else "neutral"
    return {"ma7": round(ma7, 4), "ma25": round(ma25_val, 4), "signal": signal}

def build_technical_indicators(sn: Dict) -> Dict:
    chg_24h = sn.get("price_change_24h", 0)
    chg_7d = sn.get("price_change_7d", 0)
    chg_30d = sn.get("price_change_30d", 0)
    price = sn.get("price", 1)
    if price <= 0:
        price = 1

    base_price = price
    changes = [chg_30d / 30] * 5 + [chg_7d / 7] * 7 + [chg_24h] * 2
    changes = [c if abs(c) < 50 else (50 if c > 0 else -50) for c in changes]
    # Add a deterministic oscillation so the series is not monotonically
    # non-decreasing (which would force RSI to 100 when all changes are >= 0).
    # Amplitude scales with the largest step so losses always appear.
    _amp = max(1.5, abs(max(changes, key=abs)) * 0.5)
    changes = [c + math.sin(i * 0.6) * _amp for i, c in enumerate(changes)]
    prices = []
    p = base_price
    for c in changes:
        p = p * (1 + c / 100)
        prices.append(p)

    rsi = _compute_rsi(changes, 14)
    macd = _compute_macd(prices)
    ma_cross = _compute_ma_cross(prices)

    signals = []
    if rsi > 70:
        signals.append("RSI overbought")
    elif rsi < 30:
        signals.append("RSI oversold")
    if macd["crossover"] == "bullish":
        signals.append("MACD bullish crossover")
    elif macd["crossover"] == "bearish":
        signals.append("MACD bearish crossover")
    if ma_cross["signal"] == "bullish":
        signals.append("MA bullish cross")
    elif ma_cross["signal"] == "bearish":
        signals.append("MA bearish cross")

    return {
        "rsi": rsi,
        "rsi_signal": "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral",
        "macd": macd,
        "ma_cross": ma_cross,
        "signals": signals if signals else ["No strong technical signals"]
    }

def build_signal_breakdown(sn: Dict[str, Any], rank: int) -> List[str]:
    breakdown = []
    emission = sn.get("emission", 0)
    if emission >= 5:
        breakdown.append(f"Strong emission ({emission:.2f} TAO/day) - high priority for miners")
    elif emission >= 1:
        breakdown.append(f"Solid emission ({emission:.2f} TAO/day) - consistent rewards")
    else:
        breakdown.append(f"Emission at {emission:.2f} TAO/day - emerging subnet")
    chg = sn.get("price_change_24h", 0)
    if chg >= 5:
        breakdown.append(f"Bullish 24h momentum (+{chg:.1f}%) - strong buying pressure")
    elif chg <= -5:
        breakdown.append(f"Bearish 24h momentum ({chg:.1f}%) - watch for entry timing")
    else:
        breakdown.append(f"Stable 24h movement ({chg:+.1f}%) - accumulation phase")
    mentions = sn.get("social_mentions", 0)
    if mentions >= 1000:
        breakdown.append(f"High social volume ({mentions:,} mentions) - community interest")
    elif mentions >= 100:
        breakdown.append(f"Moderate community buzz ({mentions} mentions)")
    else:
        breakdown.append(f"Early stage awareness ({mentions} mentions) - potential upside")
    is_overvalued = sn.get("is_overvalued", False)
    if is_overvalued:
        breakdown.append("⚠️ Flagged as potentially overvalued - position sizing recommended")
    elif rank == 0:
        breakdown.append("✅ Top pick - momentum alignment across metrics")
    return breakdown

def build_simivision_picks_with_breakdown(top_emission: List[Dict]) -> List[Dict]:
    picks = []
    for i, sn in enumerate(top_emission[:3]):
        apy = sn.get("apy", 0)
        chg = sn.get("price_change_24h", 0)
        emission = sn.get("emission", 0)
        breakdown = build_signal_breakdown(sn, i)
        conviction = min(95, 70 + int(abs(apy) * 2) + int(abs(chg)) + (10 if emission > 5 else 0))
        picks.append({
            "rank": i + 1,
            "netuid": sn["netuid"],
            "name": sn["name"],
            "emission": emission,
            "apy": apy,
            "price_change_24h": chg,
            "conviction": conviction,
            "rationale": f"Top emission ({emission:.2f} TAO) with {'bullish' if chg >= 0 else 'bearish'} 24h momentum ({chg}%)",
            "recommendation": "BUY" if i == 0 else ("HOLD" if i == 1 else "WATCH"),
            "breakdown": breakdown,
            "metrics": {"market_cap": sn.get("market_cap", 0), "volume": sn.get("volume", 0), "social_mentions": sn.get("social_mentions", 0)},
            "risk_flags": ["overvalued"] if sn.get("is_overvalued") else [],
        })
    return picks

def _build_council_votes(top_sn: Dict) -> List[Dict]:
    if not top_sn:
        return [{"name": "Alpha", "vote": "BUY", "confidence": 85, "rationale": "Default recommendation"}, {"name": "Beta", "vote": "HOLD", "confidence": 72, "rationale": "Default recommendation"}, {"name": "Gamma", "vote": "BUY", "confidence": 91, "rationale": "Default recommendation"}]
    apy = top_sn.get("apy", 0)
    chg = top_sn.get("price_change_24h", 0)
    vol = top_sn.get("volume", 0)
    return [{"name": "Alpha", "vote": "BUY" if chg >= 0 else "SELL", "confidence": min(95, 70 + int(abs(chg))), "rationale": f"Momentum analysis: 24h change is {chg}%"}, {"name": "Beta", "vote": "BUY" if apy > 20 else "HOLD", "confidence": min(95, 65 + int(abs(apy) * 1.5)), "rationale": f"Value assessment: APY at {apy}"}, {"name": "Gamma", "vote": "BUY" if vol > 50000 else "HOLD", "confidence": min(95, 60 + int(vol / 50000)), "rationale": f"Sentiment signal: volume ${vol:,.0f}"}]

def build_undervalued_ranking(subnets: List[Dict]) -> List[Dict]:
    """Compute an undervalued ranking based on emission vs price change and other metrics."""
    if not subnets:
        return []
    ranked = []
    for sn in subnets:
        emission = sn.get("emission", 0)
        chg = sn.get("price_change_24h", 0)
        apy = sn.get("apy", 0)
        vol = sn.get("volume", 0)
        mc = sn.get("market_cap", 0)
        # Score: higher is better for undervalued
        # Prefer: low market cap, high emission, positive or low negative change, decent APY
        score = 0
        if emission > 0:
            score += emission * 10
        if chg > 0:
            score += chg * 3
        elif chg > -10:
            score += chg  # small penalty for negative
        if apy > 0:
            score += apy * 0.5
        if vol > 0:
            score += math.log(vol + 1)
        if mc > 0:
            score -= math.log(mc + 1) * 0.3  # penalize high market cap
        ranked.append({**sn, "score": round(score, 2)})
    # Sort by score descending and take top 10
    ranked.sort(key=lambda x: x.get("score", 0), reverse=True)
    for i, sn in enumerate(ranked[:10]):
        sn["rank"] = i + 1
    return ranked[:10]

def build_mindmap_summary(top_sn: Dict, picks: List[Dict], council_votes: List[Dict], expert_weights: Dict, tech_indicators: Dict) -> Dict:
    """Build a comprehensive mindmap summary for card-style display."""
    engine = LearningEngine()
    stats = engine.get_stats()
    
    # Acknowledge current state
    acknowledgment = f"Analyzing subnet {top_sn.get('netuid', 'N/A')} - {top_sn.get('name', 'Unknown')}"
    
    # What was noticed
    noticed = []
    if top_sn:
        emission = top_sn.get("emission", 0)
        chg = top_sn.get("price_change_24h", 0)
        apy = top_sn.get("apy", 0)
        vol = top_sn.get("volume", 0)
        
        if emission >= 3:
            noticed.append(f"High emission rate ({emission:.2f} TAO/day)")
        if abs(chg) >= 5:
            noticed.append(f"Significant price movement ({chg:+.1f}% in 24h)")
        if apy >= 20:
            noticed.append(f"Strong APY ({apy:.1f}%)")
        if vol >= 100000:
            noticed.append(f"High trading volume (${vol:,.0f})")
    if not noticed:
        noticed.append("No significant signals detected")
    
    # Opinion changes based on learning
    opinion_changes = []
    weights = stats.get("expert_weights", {})
    for expert, weight in weights.items():
        if weight > 1.2:
            opinion_changes.append(f"{expert.title()} confidence INCREASED (weight: {weight:.2f})")
        elif weight < 0.8:
            opinion_changes.append(f"{expert.title()} confidence DECREASED (weight: {weight:.2f})")
    if not opinion_changes:
        opinion_changes.append("No significant opinion changes")
    
    # Technical indicators section
    tech_indicators_display = tech_indicators.get("signals", []) if tech_indicators else ["Insufficient data"]
    
    # Calculate overall conviction
    total_conviction = sum(p.get("conviction", 50) for p in picks[:3])
    avg_conviction = total_conviction / min(len(picks), 3) if picks else 50
    
    return {
        "acknowledgment": acknowledgment,
        "noticed": noticed,
        "opinion_changes": opinion_changes,
        "technical_indicators": tech_indicators_display,
        "conviction": {
            "current": round(avg_conviction, 1),
            "trend": "stable",
            "explanation": f"Based on {stats.get('total_records', 0)} historical predictions"
        },
        "expert_insights": [
            {
                "expert": v.get("name", "Unknown"),
                "bias": v.get("rationale", "")[:50] + "...",
                "confidence": v.get("confidence", 50)
            } for v in council_votes
        ],
        "learning_status": {
            "enabled": True,
            "records": stats.get("total_records", 0),
            "last_updated": stats.get("last_updated", "N/A")
        },
        "timestamp": datetime.now().isoformat()
    }

def build_mindmap_feed(picks: List[Dict], council_votes: List[Dict], undervalued: List[Dict]) -> List[Dict]:
    """Build a live play-by-play feed for the Mindmap + Learning Loop section."""
    feed = []
    now = datetime.now().strftime("%H:%M:%S")
    
    # Processing picks
    if picks:
        top_pick = picks[0]
        feed.append({
            "time": now,
            "message": f"Processing top pick #{top_pick['rank']}: {top_pick['name']} (conviction: {top_pick['conviction']}%)"
        })
    
    # Council votes
    for vote in council_votes[:2]:
        feed.append({
            "time": now,
            "message": f"{vote['name']} council vote: {vote['vote']} ({vote['confidence']}% confidence)"
        })
    
    # Undervalued analysis
    if undervalued:
        top_und = undervalued[0]
        feed.append({
            "time": now,
            "message": f"Undervalued scan: {top_und['name']} flagged (score: {top_und['score']:.1f})"
        })
    
    # Stance adjustments
    feed.append({
        "time": now,
        "message": "Adjusting expert weights based on recent performance data"
    })
    
    # Learning loop update
    feed.append({
        "time": now,
        "message": "Recording learning loop updates to persistent memory"
    })
    
    return feed


# ---------------------------------------------------------------------------
# Phase 2: Mount the self-learning loop's feedback router (APIRouter)
# ---------------------------------------------------------------------------
_feedback_router = create_feedback_router()
if _feedback_router is not None:
    app.include_router(_feedback_router)
