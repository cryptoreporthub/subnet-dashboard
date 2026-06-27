import json
import logging
import math
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Add the current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetchers.taomarketcap import get_all_subnets, get_subnet_data
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

app = FastAPI(title="SimiVision Subnet Dashboard", version="3.5.0")

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
    return {
        "status": "success",
        "tokens": _ROTATION_TOKENS,
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
    """Real learning-loop stats from the closed loop (resolve -> judge -> weights)."""
    try:
        subnets, _ = _get_subnets_with_source()
        metrics = _compute_learning_metrics(subnets)
        return {
            "status": "success",
            "data": {
                "expert_weights": metrics.get("expert_weights", {}),
                "council_weights": metrics.get("council_weights", []),
                "regime": metrics.get("regime", "chop"),
                "total_records": metrics.get("total_records", 0),
                "predictions_pending": metrics.get("predictions_pending", 0),
                "predictions_resolved": metrics.get("predictions_resolved", 0),
                "correct": metrics.get("correct", 0),
                "wrong": metrics.get("wrong", 0),
                "accuracy": metrics.get("accuracy", 0.0),
                "calibration": metrics.get("calibration", []),
                "signal_attribution": metrics.get("signal_attribution", []),
                "streaks": metrics.get("streaks", []),
                "last_updated": metrics.get("last_updated") or datetime.utcnow().isoformat() + "Z",
            },
        }
    except Exception as exc:
        logger.warning("learning stats fallback: %s", exc)
        engine = LearningEngine()
        stats = engine.get_stats()
        return {
            "status": "success",
            "data": {
                "expert_weights": stats.get("expert_weights", {}),
                "total_records": stats.get("total_records", 0),
                "last_updated": stats.get("last_updated") or datetime.utcnow().isoformat() + "Z",
            },
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
    """Adapter over the canonical PredictionStore (data/prediction_store.py).

    Delegates to the new persistent store so the closed learning loop
    (resolve -> judge -> weights) operates on the same data the dashboard
    renders. Keeps the legacy {predictions, resolved, stats} shape so the
    existing template + /api/predictions contract is preserved.
    """

    _store = None

    @classmethod
    def _store_obj(cls):
        if cls._store is None:
            from data.prediction_store import PredictionStore as _PS
            cls._store = _PS(_PREDICTIONS_PATH)
        return cls._store

    @staticmethod
    def _load() -> Dict[str, Any]:
        return PREDICTION_STORE._store_obj().all()

    @staticmethod
    def _save(data: Dict[str, Any]) -> None:
        # The canonical store is the source of truth; this is a no-op kept
        # for legacy callers that round-trip _load() -> mutate -> _save().
        pass

    @staticmethod
    def add(prediction: Dict[str, Any]) -> Dict[str, Any]:
        return PREDICTION_STORE._store_obj().add_prediction(prediction)

    @staticmethod
    def all() -> List[Dict[str, Any]]:
        return PREDICTION_STORE._store_obj().get_pending()

    @staticmethod
    def resolved() -> List[Dict[str, Any]]:
        return PREDICTION_STORE._store_obj().get_resolved()

    @staticmethod
    def update_stats(data: Dict[str, Any]) -> None:
        # Stats are recomputed by the canonical store on every read.
        stats = PREDICTION_STORE._store_obj().get_stats()
        data["stats"] = stats


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

    Uses real candles from price_cache.json when available; otherwise
    synthesises a series from the subnet's price + 24h/7d/30d changes so the
    simplified RSI fallback and other indicators still produce values.
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
                steps.append(chg_30d / 30.0)
            elif i < 22:
                steps.append(chg_7d / 7.0)
            else:
                steps.append(chg_24h)
        steps = [s if abs(s) < 50 else (50 if s > 0 else -50) for s in steps]
        p = price
        synth_closes = []
        for s in steps:
            p = p * (1 + s / 100.0)
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
    """Proper Wilder RSI from close prices. Falls back to 50.0 on short history."""
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
    """Estimate predicted directional impact per signal type using SIGNAL_TYPES half-lives."""
    impacts: List[Dict[str, Any]] = []
    chg = float(sn.get("price_change_24h", 0) or 0)

    def _freshness(half_life_hours: float, age_hours: float = 1.0) -> float:
        if half_life_hours <= 0:
            return 1.0
        return round(0.5 ** (age_hours / half_life_hours), 3)

    rsi = indicators.get("rsi", {})
    if isinstance(rsi, dict) and rsi.get("signal") in ("oversold", "overbought"):
        st = SIGNAL_TYPES.get("rsi_crossover", {})
        direction = "bullish" if rsi.get("signal") == "oversold" else "bearish"
        mag = round(abs(50 - rsi.get("value", 50)) * 0.1, 2)
        impacts.append({
            "signal_type": "rsi_crossover",
            "description": st.get("description", "RSI crossover"),
            "direction": direction,
            "magnitude_pct": mag,
            "freshness": _freshness(st.get("half_life_hours", 24)),
            "predicted_move": f"predicted to move {'+' if direction == 'bullish' else '-'}{mag:.1f}% within 24 hours",
        })
    macd = indicators.get("macd", {})
    if isinstance(macd, dict) and macd.get("crossover") in ("bullish", "bearish"):
        st = SIGNAL_TYPES.get("macd_cross", {})
        direction = macd.get("crossover")
        mag = round(abs(macd.get("histogram", 0)) * 10, 2)
        impacts.append({
            "signal_type": "macd_cross",
            "description": st.get("description", "MACD cross"),
            "direction": direction,
            "magnitude_pct": mag,
            "freshness": _freshness(st.get("half_life_hours", 48)),
            "predicted_move": f"predicted to move {'+' if direction == 'bullish' else '-'}{mag:.1f}% within 48 hours",
        })
    stoch = indicators.get("stochastic", {})
    if isinstance(stoch, dict) and stoch.get("signal") in ("oversold", "overbought"):
        st = SIGNAL_TYPES.get("stochastic_reversal", {})
        direction = "bullish" if stoch.get("signal") == "oversold" else "bearish"
        mag = round(abs(50 - stoch.get("k", 50)) * 0.08, 2)
        impacts.append({
            "signal_type": "stochastic_reversal",
            "description": st.get("description", "Stochastic reversal"),
            "direction": direction,
            "magnitude_pct": mag,
            "freshness": _freshness(st.get("half_life_hours", 8)),
            "predicted_move": f"predicted to move {'+' if direction == 'bullish' else '-'}{mag:.1f}% within 8 hours",
        })
    if abs(chg) >= 5:
        st = SIGNAL_TYPES.get("momentum_shift", {})
        direction = "bullish" if chg > 0 else "bearish"
        mag = round(abs(chg) * 0.5, 2)
        impacts.append({
            "signal_type": "momentum_shift",
            "description": st.get("description", "Momentum shift"),
            "direction": direction,
            "magnitude_pct": mag,
            "freshness": _freshness(st.get("half_life_hours", 12)),
            "predicted_move": f"predicted to move {'+' if direction == 'bullish' else '-'}{mag:.1f}% within 12 hours",
        })
    emission = float(sn.get("emission", 0) or 0)
    if emission > 3:
        st = SIGNAL_TYPES.get("emission_change", {})
        mag = round(emission * 0.3, 2)
        impacts.append({
            "signal_type": "emission_change",
            "description": st.get("description", "Emission change"),
            "direction": "bullish",
            "magnitude_pct": mag,
            "freshness": _freshness(st.get("half_life_hours", 168)),
            "predicted_move": f"predicted to move +{mag:.1f}% within 168 hours",
        })

    net = sum(i.get("magnitude_pct", 0) * (1 if i.get("direction") == "bullish" else -1) for i in impacts)
    return {
        "impacts": impacts,
        "net_predicted_pct": round(net, 2),
        "net_direction": "bullish" if net > 0 else "bearish" if net < 0 else "neutral",
        "hot_active": bool(hot.get("active")),
        "sell_active": bool(sell.get("active")),
        "dominant": "SELL ALERT" if sell.get("active") else ("HOT" if hot.get("active") else None),
    }


# ---------------------------------------------------------------------------
# Pattern recognition — 7 pattern types
# ---------------------------------------------------------------------------
def _detect_patterns(closes: List[float], highs: List[float], lows: List[float]) -> List[Dict[str, Any]]:
    if len(closes) < 5:
        return [{"pattern": "insufficient_data", "type": "neutral", "description": "Not enough price history", "confidence": 0}]
    found: List[Dict[str, Any]] = []
    c1, c2 = closes[-1], closes[-2]
    h1, l1 = highs[-1], lows[-1]
    body1 = abs(c1 - c2)
    range1 = h1 - l1 if h1 - l1 > 0 else 1e-9
    prev_body = abs(c2 - closes[-3]) if len(closes) > 2 else 0

    if c2 < c1 and body1 > prev_body:
        found.append({"pattern": "bullish_engulfing", **PATTERN_DEFS["bullish_engulfing"], "confidence": 72})
    if c2 > c1 and body1 > prev_body:
        found.append({"pattern": "bearish_engulfing", **PATTERN_DEFS["bearish_engulfing"], "confidence": 72})
    lower_wick = min(c1, c2) - l1
    if lower_wick > body1 * 2 and c1 > c2:
        found.append({"pattern": "hammer", **PATTERN_DEFS["hammer"], "confidence": 65})
    upper_wick = h1 - max(c1, c2)
    if upper_wick > body1 * 2 and c1 < c2:
        found.append({"pattern": "shooting_star", **PATTERN_DEFS["shooting_star"], "confidence": 65})
    if body1 <= range1 * 0.1:
        found.append({"pattern": "doji", **PATTERN_DEFS["doji"], "confidence": 60})

    window = closes[-10:]
    if len(window) >= 6:
        mx = max(window)
        mn = min(window)
        peaks = [i for i, v in enumerate(window) if v >= mx * 0.98]
        troughs = [i for i, v in enumerate(window) if v <= mn * 1.02]
        if len(peaks) >= 2 and (peaks[-1] - peaks[0]) >= 3:
            found.append({"pattern": "double_top", **PATTERN_DEFS["double_top"], "confidence": 68})
        if len(troughs) >= 2 and (troughs[-1] - troughs[0]) >= 3:
            found.append({"pattern": "double_bottom", **PATTERN_DEFS["double_bottom"], "confidence": 68})

    if not found:
        found.append({"pattern": "none", "type": "neutral", "description": "No clear pattern detected", "confidence": 0})
    return found


# ---------------------------------------------------------------------------
# Predictive engine — generate / resolve / learn
# ---------------------------------------------------------------------------
def _generate_prediction(sn: Dict[str, Any], signal_impact: Dict[str, Any]) -> Dict[str, Any]:
    """Create a PREDICTIVE forecast: 'predicted to move +X% within N hours'."""
    net = signal_impact.get("net_predicted_pct", 0)
    raw_direction = signal_impact.get("net_direction", "neutral")
    # Map impact direction (bullish/bearish/neutral) -> prediction direction (up/down).
    if raw_direction == "bullish":
        direction = "up"
    elif raw_direction == "bearish":
        direction = "down"
    else:
        direction = "up" if float(sn.get("price_change_24h", 0) or 0) >= 0 else "down"
    magnitude = abs(net) if net != 0 else 1.5
    horizon = 24
    impacts = signal_impact.get("impacts", [])
    if impacts:
        strongest = max(impacts, key=lambda i: i.get("magnitude_pct", 0))
        st = SIGNAL_TYPES.get(strongest.get("signal_type", ""), {})
        horizon = int(st.get("half_life_hours", 24))

    predicted_pct = magnitude if direction == "up" else -magnitude
    ref_price = float(sn.get("price", 0) or 0) or 1.0
    now_dt = _dt.utcnow()
    due_dt = now_dt + _td(hours=horizon)

    # Rich schema for the closed learning loop: conviction, contributing
    # experts, signal tags and human-readable reasons flow into judging,
    # calibration buckets and signal attribution.
    chg = float(sn.get("price_change_24h", 0) or 0)
    conviction = min(95, 70 + int(abs(chg)) + int(float(sn.get("apy", 0) or 0) / 4) + (8 if signal_impact.get("dominant") else 0))
    experts_involved = []
    if signal_impact.get("dominant"):
        experts_involved.append("technical")
    if abs(chg) >= 5 or float(sn.get("apy", 0) or 0) >= 20:
        experts_involved.append("quant")
    if float(sn.get("volume", 0) or 0) > 0:
        experts_involved.append("hype")
    if direction == "down":
        experts_involved.append("contrarian")
    experts_involved = list(dict.fromkeys(experts_involved)) or ["technical"]

    signal_tags = []
    for imp in impacts:
        stype = imp.get("signal_type")
        if stype:
            signal_tags.append(stype)
    if not signal_tags and signal_impact.get("dominant"):
        signal_tags = [signal_impact["dominant"]]

    reasons = []
    if impacts:
        for imp in impacts[:3]:
            stype = imp.get("signal_type", "")
            mag = imp.get("magnitude_pct", 0)
            reasons.append(f"{stype} {mag:+.1f}%")
    if not reasons:
        reasons = [f"{direction} bias from {chg:+.1f}% 24h move"]

    prediction = {
        "id": _uuid.uuid4().hex[:10],
        "netuid": sn.get("netuid"),
        "name": sn.get("name"),
        "subnet": sn.get("name"),
        "direction": direction,
        "predicted_pct": round(predicted_pct, 2),
        "horizon_hours": horizon,
        "reference_price": ref_price,
        "reference_time": now_dt.isoformat() + "Z",
        "due_time": due_dt.isoformat() + "Z",
        "created_at": now_dt.isoformat() + "Z",
        "resolve_at": due_dt.isoformat() + "Z",
        "status": "pending",
        "conviction": conviction,
        "experts_involved": experts_involved,
        "signal_tags": signal_tags,
        "reasons": reasons,
        "signal_source": signal_impact.get("dominant") or direction,
        "statement": f"predicted to move {'+' if predicted_pct >= 0 else ''}{predicted_pct:.1f}% within {horizon} hours",
    }
    PREDICTION_STORE.add(prediction)
    return prediction


def _resolve_prediction(prediction: Dict[str, Any], latest_price: float) -> Dict[str, Any]:
    """Resolve a pending prediction against the latest available price.

    Delegates classification to OutcomeResolver so the outcome label
    (correct/partial/wrong/expired) is consistent with the closed loop.
    """
    from data.outcome_resolver import OutcomeResolver
    classification = OutcomeResolver.classify(prediction, latest_price or 0)
    resolution = {
        **classification,
        "resolved_at": _dt.utcnow().isoformat() + "Z",
        "reference_price": float(prediction.get("reference_price", 0) or 0),
        "predicted_pct": float(prediction.get("predicted_pct", 0) or 0),
        "direction": prediction.get("direction"),
        "netuid": prediction.get("netuid"),
        "subnet": prediction.get("subnet") or prediction.get("name"),
    }
    store = PREDICTION_STORE._store_obj()
    resolved = store.resolve(prediction.get("id"), resolution) or prediction
    # Judge immediately so weights reflect the freshest outcome.
    try:
        from internal.council.learner import get_scheduler
        sched = get_scheduler()
        verdict = sched.judge.judge_prediction(resolved, resolution)
        sched.judge.update_council_weights(verdict)
        sched.judge.persist()
    except Exception as exc:
        logger.warning("Immediate judging failed: %s", exc)
    return resolved


def _update_learning_weights(correct: bool, source: str = None) -> Dict[str, Any]:
    """Adjust Council expert weights via the adversarial judge.

    Kept for legacy callers; the canonical path is the scheduler's
    update_council_weights() which applies +0.02/-0.03/+0.005 with
    normalization, dampening and recency weighting.
    """
    try:
        from internal.council.learner import get_scheduler
        sched = get_scheduler()
        outcome = "correct" if correct else "wrong"
        verdict = {
            "outcome": outcome,
            "experts_involved": ["quant", "hype", "contrarian", "technical"],
            "signal_tags": [source] if source else [],
        }
        weights = sched.judge.update_council_weights(verdict)
        sched.judge.persist()
        delta = _LEARNING_DELTA_CORRECT if correct else _LEARNING_DELTA_WRONG
        return {"updated": True, "delta": delta, "correct": correct, "weights": weights}
    except Exception as exc:
        logger.warning("Learning weight update failed: %s", exc)
        delta = _LEARNING_DELTA_CORRECT if correct else _LEARNING_DELTA_WRONG
        return {"updated": False, "delta": delta, "correct": correct}


def _resolve_due_predictions(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Resolve pending predictions whose horizon has elapsed.

    Runs the closed learning loop: resolve -> judge -> update weights ->
    persist. Falls back to the live subnet snapshot for prices when the
    taomarketcap fetcher is unavailable.
    """
    from internal.council.learner import get_scheduler
    sched = get_scheduler()
    # Prefer live snapshot prices (already fetched) over re-fetching per netuid.
    price_by_netuid = {sn.get("netuid"): float(sn.get("price", 0) or 0) for sn in subnets}

    def _provider(netuid):
        return price_by_netuid.get(netuid) or None

    # Temporarily swap the resolver's price provider to use the live snapshot.
    original_provider = sched.resolver.price_provider
    sched.resolver.price_provider = _provider
    try:
        resolved = sched.resolver.resolve_due_predictions()
        for entry in resolved:
            try:
                resolution = entry.get("resolution") or {}
                verdict = sched.judge.judge_prediction(entry, resolution)
                sched.judge.update_council_weights(verdict)
            except Exception as exc:
                logger.warning("judge failed for %s: %s", entry.get("id"), exc)
        try:
            sched.judge.persist()
        except Exception as exc:
            logger.warning("judge persist failed: %s", exc)
    finally:
        sched.resolver.price_provider = original_provider
    return resolved


# ---------------------------------------------------------------------------
# Learning loop metrics
# ---------------------------------------------------------------------------
def _market_data_for_regime(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate market intelligence for regime detection."""
    if not subnets:
        return {}
    changes = [float(s.get("price_change_24h", 0) or 0) for s in subnets]
    gainers = sum(1 for c in changes if c > 0)
    losers = sum(1 for c in changes if c < 0)
    avg = sum(changes) / len(changes) if changes else 0
    breadth = "bullish" if gainers > losers * 1.5 and avg > 2 else (
        "bearish" if losers > gainers * 1.5 and avg < -2 else "neutral"
    )
    volatility = (sum((c - avg) ** 2 for c in changes) / len(changes)) ** 0.5 if changes else 0
    return {
        "avg_change_24h": round(avg, 2),
        "breadth": breadth,
        "gainers": gainers,
        "losers": losers,
        "volatility": round(volatility, 2),
    }


def _compute_learning_metrics(subnets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Real learning-loop metrics from the closed loop.

    Pulls expert weights, accuracy, calibration buckets, signal attribution,
    regime and streaks from the LearningLoopScheduler so the dashboard
    reflects the actual self-learning state (not empty placeholders).
    """
    from internal.council.learner import get_scheduler
    market_data = _market_data_for_regime(subnets or [])
    try:
        status = get_scheduler().status(market_data=market_data)
    except Exception as exc:
        logger.warning("learning status failed: %s", exc)
        status = {}

    store = PREDICTION_STORE._store_obj()
    resolved = store.get_resolved()
    recent = resolved[-10:]
    weights = status.get("expert_weights", {}) or {}

    # Build the council_weights panel from learned weights + regime adjustment.
    from internal.council.weights import apply_regime_adjustment
    regime = status.get("regime", "chop")
    adjusted = apply_regime_adjustment(weights, regime) if weights else {}
    council_weights = [
        {
            "expert": k.title(),
            "weight": round(v, 3),
            "adjusted": round(adjusted.get(k, v), 3),
            "bias": "bullish" if v >= 1.0 else "cautious",
        }
        for k, v in weights.items()
    ]

    accuracy = status.get("accuracy_pct", 0.0)
    return {
        "expert_weights": weights,
        "council_weights": council_weights,
        "regime": regime,
        "total_records": status.get("resolved", 0),
        "predictions_pending": status.get("pending", 0),
        "predictions_resolved": status.get("resolved", 0),
        "correct": status.get("correct", 0),
        "partial": status.get("partial", 0),
        "wrong": status.get("wrong", 0),
        "expired": status.get("expired", 0),
        "accuracy": accuracy,
        "accuracy_pct": accuracy,
        "calibrating": status.get("resolved", 0) == 0,
        "deltas": {"correct": _LEARNING_DELTA_CORRECT, "wrong": _LEARNING_DELTA_WRONG, "partial": 0.005},
        "calibration": status.get("calibration", []),
        "signal_attribution": status.get("signal_attribution", []),
        "streaks": status.get("expert_accuracy", []),
        "recent_resolutions": [
            {
                "name": r.get("subnet") or r.get("name"),
                "predicted_pct": r.get("predicted_pct"),
                "actual_pct": (r.get("resolution") or {}).get("actual_pct"),
                "outcome": r.get("outcome"),
                "correct": r.get("outcome") == "correct",
                "statement": r.get("statement"),
                "failure_tags": (r.get("resolution") or {}).get("note"),
            } for r in recent
        ],
        "last_updated": status.get("last_run"),
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
    desc = str(sn.get("description", "") or "")
    base_label = _classify_sentiment(desc)
    if chg > 5:
        bias = "bullish"
    elif chg < -5:
        bias = "bearish"
    else:
        bias = base_label
    score = 50 + (20 if bias == "bullish" else -20 if bias == "bearish" else 0) + int(chg)
    score = max(0, min(100, score))
    feed = [
        {"source": "twitter", "sentiment": bias, "text": f"${sn.get('name','SN')} momentum {'building' if bias=='bullish' else 'fading' if bias=='bearish' else 'mixed'} — {chg:+.1f}% 24h", "mentions": mentions},
        {"source": "discord", "sentiment": base_label, "text": (desc[:90] + "...") if len(desc) > 90 else (desc or "Community discussion active"), "mentions": max(0, mentions // 2)},
        {"source": "reddit", "sentiment": bias if bias != "neutral" else "neutral", "text": f"Validator chatter around SN{sn.get('netuid')} emission {sn.get('emission', 0)} TAO/day", "mentions": max(0, mentions // 3)},
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

    try:
        _resolve_due_predictions(subnets)
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
        patterns = _detect_patterns(hist.get("closes", []), hist.get("highs", []), hist.get("lows", []))
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
    learning_metrics = _compute_learning_metrics(subnets)
    momentum_charts = _build_momentum_charts(subnets, simivision_picks)

    # Learned weights are the canonical source of truth (soul_map.json via
    # the adversarial judge). The selector reads these on the next pick.
    expert_weights = learning_metrics.get("expert_weights", {}) or {}
    council_weights = learning_metrics.get("council_weights", []) or [
        {"expert": "Quant", "weight": 1.0, "bias": "bullish"},
        {"expert": "Hype", "weight": 1.0, "bias": "cautious"},
        {"expert": "Contrarian", "weight": 1.0, "bias": "bullish"},
        {"expert": "Technical", "weight": 1.0, "bias": "bullish"},
    ]
    regime = learning_metrics.get("regime", "chop")

    mindmap_trail = []
    for p in simivision_picks[:4]:
        mindmap_trail.append({
            "time": _dt.utcnow().strftime("%H:%M:%S"),
            "subnet": p.get("name"),
            "evidence": p.get("reasons", [])[0] if p.get("reasons") else "metrics scanned",
            "signal": p.get("signal_impact", {}).get("dominant") or p.get("signal_impact", {}).get("net_direction"),
            "decision": p.get("recommendation"),
            "prediction": p.get("prediction", {}).get("statement"),
            "judge": f"conviction {p.get('conviction')}%",
        })
    mindmap_trail.append({
        "time": _dt.utcnow().strftime("%H:%M:%S"),
        "subnet": "—",
        "evidence": "Learning loop",
        "signal": f"accuracy {learning_metrics.get('accuracy', 0)}",
        "decision": "weight update",
        "prediction": f"correct +{_LEARNING_DELTA_CORRECT} / wrong {_LEARNING_DELTA_WRONG}",
        "judge": f"{learning_metrics.get('correct', 0)} correct / {learning_metrics.get('wrong', 0)} wrong",
    })

    # Cemetery = wrong (false-positive) predictions, surfaced for transparency.
    try:
        cemetery = PREDICTION_STORE._store_obj().get_cemetery(limit=20)
    except Exception:
        cemetery = []

    return {
        "simivision_picks": simivision_picks,
        "undervalued_radar": undervalued,
        "technical_indicators": technical_panel,
        "market_intelligence": market_intel,
        "staking_analytics": staking,
        "council_weights": council_weights,
        "expert_weights": expert_weights,
        "regime": regime,
        "mindmap_trail": mindmap_trail,
        "signal_impact": signal_impacts,
        "patterns": patterns_all,
        "predictions": predictions,
        "learning_metrics": learning_metrics,
        "cemetery": cemetery,
        "calibration": learning_metrics.get("calibration", []),
        "signal_attribution": learning_metrics.get("signal_attribution", []),
        "streaks": learning_metrics.get("streaks", []),
        "social_sentiment": social_feed,
        "indicators_convergence": {
            "oversold": _detect_oversold_convergence(_compute_technical_indicators(top_subnets[0])) if top_subnets else {},
            "overbought": _detect_overbought_convergence(_compute_technical_indicators(top_subnets[0])) if top_subnets else {},
        },
        "momentum_charts": momentum_charts,
    }



@app.get("/")
async def dashboard(request: Request):
    """Render the SimiVision dashboard server-side via Jinja2.

    Context flows: server fetches subnets + SimiVision picks + mindmap summary
    + learning stats -> renders into templates/index.html -> user sees the
    complete dashboard. Vanilla JS polls /api/subnets every 5 min for refresh.
    """
    try:
        subnets, source = _get_subnets_with_source()
        premium = _build_premium_context(subnets)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "subnets": subnets,
                "data_source": source,
                "mindmap": get_mindmap_summary(),
                "learning_stats": get_learning_stats(),
                "simivision": get_simivision_data(),
                "rotation_tokens": _ROTATION_TOKENS,
                "simivision_picks": premium["simivision_picks"],
                "undervalued_radar": premium["undervalued_radar"],
                "technical_indicators": premium["technical_indicators"],
                "market_intelligence": premium["market_intelligence"],
                "staking_analytics": premium["staking_analytics"],
                "council_weights": premium["council_weights"],
                "expert_weights": premium["expert_weights"],
                "regime": premium["regime"],
                "mindmap_trail": premium["mindmap_trail"],
                "signal_impact": premium["signal_impact"],
                "patterns": premium["patterns"],
                "predictions": premium["predictions"],
                "learning_metrics": premium["learning_metrics"],
                "cemetery": premium["cemetery"],
                "calibration": premium["calibration"],
                "signal_attribution": premium["signal_attribution"],
                "streaks": premium["streaks"],
                "social_sentiment": premium["social_sentiment"],
                "indicators_convergence": premium["indicators_convergence"],
                "momentum_charts": premium["momentum_charts"],
            },
        )
    except Exception as e:
        logger.error("Error rendering dashboard: %s", e)
        return PlainTextResponse(
            f"Internal Server Error: {str(e)}\nSystem status: Not operative",
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


# ---------------------------------------------------------------------------
# Learning Loop — background scheduler + closed-loop API endpoints
# ---------------------------------------------------------------------------

import threading as _threading

_LEARNING_INTERVAL_SECONDS = 30 * 60  # every 30 minutes
_LEARNER_THREAD = None
_LEARNER_STOP = _threading.Event()


def _run_learning_loop_once() -> Dict[str, Any]:
    """Run one pass of the closed learning loop (resolve -> judge -> weights).

    Uses the live subnet snapshot for prices so we don't re-fetch per netuid.
    """
    try:
        from internal.council.learner import get_scheduler
        subnets, _ = _get_subnets_with_source()
        market_data = _market_data_for_regime(subnets)
        price_by_netuid = {sn.get("netuid"): float(sn.get("price", 0) or 0) for sn in subnets}

        sched = get_scheduler()
        original_provider = sched.resolver.price_provider
        sched.resolver.price_provider = lambda netuid: price_by_netuid.get(netuid) or None
        try:
            summary = sched.run(market_data=market_data)
        finally:
            sched.resolver.price_provider = original_provider
        logger.info("learning loop ran: %s", summary)
        return summary
    except Exception as exc:
        logger.warning("learning loop run failed: %s", exc)
        return {"error": str(exc)}


def _learning_loop_worker() -> None:
    """Background worker: run the learning loop every 30 minutes."""
    while not _LEARNER_STOP.is_set():
        try:
            _run_learning_loop_once()
        except Exception as exc:
            logger.warning("learning loop worker error: %s", exc)
        _LEARNER_STOP.wait(_LEARNING_INTERVAL_SECONDS)


def _start_learning_loop() -> None:
    """Start the background learning loop (idempotent, daemon thread)."""
    global _LEARNER_THREAD
    if _LEARNER_THREAD is not None and _LEARNER_THREAD.is_alive():
        return
    _LEARNER_STOP.clear()
    _LEARNER_THREAD = _threading.Thread(target=_learning_loop_worker, name="learning-loop", daemon=True)
    _LEARNER_THREAD.start()
    logger.info("learning loop scheduler started (interval=%ss)", _LEARNING_INTERVAL_SECONDS)


@app.on_event("startup")
async def _startup_learning_loop() -> None:
    """Boot the self-learning loop on app start so predictions resolve + judge."""
    try:
        _start_learning_loop()
    except Exception as exc:
        logger.warning("Failed to start learning loop: %s", exc)


@app.get("/api/learning/stats")
async def api_learning_stats():
    """Real learning-loop stats: weights, accuracy, calibration, regime, streaks."""
    try:
        subnets, _ = _get_subnets_with_source()
        return _compute_learning_metrics(subnets)
    except Exception as e:
        logger.error("Error fetching learning stats: %s", e)
        return {"error": str(e), "expert_weights": {}, "accuracy": 0.0}


@app.get("/api/predictions/pending")
async def api_predictions_pending():
    """Return all pending (unresolved) predictions."""
    try:
        return {"predictions": PREDICTION_STORE.all(), "count": len(PREDICTION_STORE.all())}
    except Exception as e:
        logger.error("Error fetching pending predictions: %s", e)
        return {"predictions": [], "count": 0, "error": str(e)}


@app.get("/api/predictions/resolved")
async def api_predictions_resolved():
    """Return all resolved predictions (correct/partial/wrong/expired)."""
    try:
        resolved = PREDICTION_STORE.resolved()
        return {"resolved": resolved, "count": len(resolved)}
    except Exception as e:
        logger.error("Error fetching resolved predictions: %s", e)
        return {"resolved": [], "count": 0, "error": str(e)}


@app.get("/api/learning/cemetery")
async def api_learning_cemetery():
    """Wrong (false-positive) predictions — the learning cemetery."""
    try:
        cemetery = PREDICTION_STORE._store_obj().get_cemetery(limit=100)
        return {"cemetery": cemetery, "count": len(cemetery)}
    except Exception as e:
        logger.error("Error fetching cemetery: %s", e)
        return {"cemetery": [], "count": 0, "error": str(e)}


@app.get("/api/learning/calibration")
async def api_learning_calibration():
    """Conviction-vs-accuracy calibration buckets."""
    try:
        from internal.council.learner import get_scheduler
        buckets = get_scheduler().judge.get_calibration_buckets()
        return {"calibration": buckets}
    except Exception as e:
        logger.error("Error fetching calibration: %s", e)
        return {"calibration": [], "error": str(e)}


@app.get("/api/learning/signals")
async def api_learning_signals():
    """Per-signal-tag accuracy attribution."""
    try:
        from internal.council.learner import get_scheduler
        attribution = get_scheduler().judge.get_signal_attribution()
        return {"signal_attribution": attribution}
    except Exception as e:
        logger.error("Error fetching signal attribution: %s", e)
        return {"signal_attribution": [], "error": str(e)}


@app.get("/api/learning/regime")
async def api_learning_regime():
    """Current market regime classification."""
    try:
        from internal.council.weights import detect_regime
        subnets, _ = _get_subnets_with_source()
        market_data = _market_data_for_regime(subnets)
        regime = detect_regime(market_data)
        return {"regime": regime, "market_data": market_data}
    except Exception as e:
        logger.error("Error fetching regime: %s", e)
        return {"regime": "chop", "error": str(e)}


@app.get("/api/learning/streaks")
async def api_learning_streaks():
    """Expert leaderboard: accuracy, current/best streaks."""
    try:
        from internal.council.learner import get_scheduler
        streaks = get_scheduler().judge.get_streaks()
        return {"streaks": streaks}
    except Exception as e:
        logger.error("Error fetching streaks: %s", e)
        return {"streaks": [], "error": str(e)}


@app.post("/api/learning/run")
async def api_learning_run():
    """Manually trigger one learning-loop pass (resolve -> judge -> weights)."""
    try:
        summary = _run_learning_loop_once()
        return {"status": "success", "summary": summary}
    except Exception as e:
        logger.error("Error running learning loop: %s", e)
        return {"status": "error", "error": str(e)}
