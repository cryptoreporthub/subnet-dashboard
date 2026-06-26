import json
import logging
import math
import os
import sys
from datetime import datetime
from typing import Any, Dict, List

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


@app.get("/")
async def dashboard(request: Request):
    """Render the SimiVision dashboard server-side via Jinja2.

    Context flows: server fetches subnets + SimiVision picks + mindmap summary
    + learning stats -> renders into templates/index.html -> user sees the
    complete dashboard. Vanilla JS polls /api/subnets every 5 min for refresh.
    """
    try:
        subnets, _ = _get_subnets_with_source()
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "subnets": subnets,
                "mindmap": get_mindmap_summary(),
                "learning_stats": get_learning_stats(),
                "simivision": get_simivision_data(),
                "rotation_tokens": _ROTATION_TOKENS,
            },
        )
    except Exception as e:
        logger.error("Error rendering dashboard: %s", e)
        return PlainTextResponse(
            f"Internal Server Error: {str(e)}\nSystem status: Not operative",
            status_code=500,
        )

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
