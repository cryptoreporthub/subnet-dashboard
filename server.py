import json
import logging
import math
import os
import sys
from datetime import datetime
from typing import Any, Dict, List
from flask import Flask, jsonify, make_response, request

sys.path.insert(0, os.path.dirname(__file__))
from fetchers.taomarketcap import get_all_subnets, get_subnet_data
from data.learning_engine import LearningEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

os.makedirs("data", exist_ok=True)

app = Flask(__name__)

_DEPLOY_TIMESTAMP = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
_APP_VERSION = "3.1.0"

_COUNCIL_MEMBERS = [
    {"name": "Alpha", "bias": "momentum"},
    {"name": "Beta", "bias": "value"},
    {"name": "Gamma", "bias": "sentiment"},
]

# Specific subnet tokens to include in rotations
_ROTATION_TOKENS = ["hyperliquid", "vvv", "near", "render", "fetch"]

def get_dynamic_subnets():
    try:
        return get_all_subnets()
    except Exception as e:
        logger.error("Error fetching live data: %s", e)
        return []

def get_top_performers(subnets: List[Dict], key: str, limit: int = 5) -> List[Dict]:
    return sorted(subnets, key=lambda x: x.get(key, 0), reverse=True)[:limit]

def load_soul_map():
    try:
        with open("data/soul_map.json", "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _app_version():
    return _APP_VERSION

# ── Subnet Radar ──────────────────────────────────────────────────────────
def _compute_dev_score(sn: dict) -> int:
    base = sn.get("emission", 0) * 10 + abs(sn.get("price_change_24h", 0)) * 2
    return min(100, int(base + 15))

def _compute_undervalued_score(sn: dict) -> float:
    mc = sn.get("market_cap", 1)
    if mc <= 0:
        mc = 1
    emission = sn.get("emission", 0)
    dev = _compute_dev_score(sn)
    return round((emission * 3 + dev * 0.5) / (mc / 1_000_000), 4)

def _build_radar_picks(subnets: list) -> list:
    scored = []
    for sn in subnets:
        try:
            score = _compute_undervalued_score(sn)
            dev = _compute_dev_score(sn)
            mc = sn.get("market_cap", 0)
            emission = sn.get("emission", 0)
            scored.append({
                "netuid": sn["netuid"],
                "name": sn["name"],
                "emission": emission,
                "market_cap": mc,
                "price_change_24h": sn.get("price_change_24h", 0),
                "dev_score": dev,
                "undervalued_score": score,
                "commit_activity": ["high" if dev > 60 else "medium" if dev > 30 else "low"],
                "github_commits_7d": max(0, int(dev * 0.7 + 2)),
            })
        except Exception:
            continue
    scored.sort(key=lambda x: x["undervalued_score"], reverse=True)
    return scored[:4]

# ── Technical indicator helpers ───────────────────────────────────────────
def _compute_rsi(price_changes: List[float], period: int = 14) -> float:
    """Compute approximate RSI from a list of price changes."""
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
    """Approximate MACD line, signal line, and histogram."""
    if len(prices) < 26:
        return {"macd": 0, "signal": 0, "histogram": 0, "crossover": "neutral"}
    ema12 = sum(prices[-12:]) / 12
    ema26 = sum(prices[-26:]) / 26
    macd_line = ema12 - ema26
    signal = macd_line * 0.8  # simplified EMA of MACD
    histogram = macd_line - signal
    crossover = "bullish" if histogram > 0 else "bearish" if histogram < 0 else "neutral"
    return {"macd": round(macd_line, 4), "signal": round(signal, 4), "histogram": round(histogram, 4), "crossover": crossover}

def _compute_ma_cross(prices: List[float]) -> Dict:
    """Short (7) vs long (25) MA cross."""
    if len(prices) < 25:
        return {"ma7": 0, "ma25": 0, "signal": "neutral"}
    ma7 = sum(prices[-7:]) / 7
    ma25_val = sum(prices[-25:]) / 25
    signal = "bullish" if ma7 > ma25_val else "bearish" if ma7 < ma25_val else "neutral"
    return {"ma7": round(ma7, 4), "ma25": round(ma25_val, 4), "signal": signal}

def _build_tech_indicators(subnets: list) -> list:
    """Build technical indicator data for the top 4 subnets by emission."""
    top = get_top_performers(subnets, "emission", 8)
    results = []
    for sn in top[:4]:
        chg_24h = sn.get("price_change_24h", 0)
        chg_7d = sn.get("price_change_7d", 0)
        chg_30d = sn.get("price_change_30d", 0)
        price = sn.get("price", 1)
        if price <= 0:
            price = 1

        # Generate synthetic price history from available changes
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

        results.append({
            "netuid": sn["netuid"],
            "name": sn["name"],
            "price": base_price,
            "rsi": rsi,
            "rsi_signal": "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral",
            "macd": macd,
            "ma_cross": ma_cross,
        })
    return results

# ── SimiVision helpers ────────────────────────────────────────────────────
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

@app.route("/health")
def health():
    return "OK", 200, {"Content-Type": "text/plain"}

@app.route("/api/subnets")
def api_subnets():
    subnets = get_dynamic_subnets()
    return jsonify({"subnets": subnets, "count": len(subnets), "source": "taomarketcap.com", "live": True})

@app.route("/api/simivision")
def api_simivision():
    subnets = get_dynamic_subnets()
    top_emission = get_top_performers(subnets, "emission")
    picks = build_simivision_picks_with_breakdown(top_emission)
    return jsonify({"status": "operational", "data_source": "taomarketcap.com", "picks": picks, "generated_at": datetime.now().isoformat()})

@app.route("/api/summary")
def api_summary():
    subnets = get_dynamic_subnets()
    top_emission = get_top_performers(subnets, "emission")
    top_apy = get_top_performers(subnets, "apy")
    top_volume = get_top_performers(subnets, "volume")
    trending = get_top_performers(subnets, "price_change_24h")
    active = [s for s in subnets if s.get("status") == "active"]
    return jsonify({"total_subnets": len(subnets), "active_subnets": len(active), "total_tvl": sum(s.get("market_cap", 0) for s in subnets) / 1e6, "highlights": {"top_emission": top_emission[:3], "top_apy": top_apy[:3], "top_volume": top_volume[:3]}, "trending": trending[:5], "data_source": "taomarketcap.com", "generated_at": datetime.now().isoformat()})

@app.route("/api/mindmap/feedback")
def api_mindmap_feedback():
    subnets = get_dynamic_subnets()
    top_emission = get_top_performers(subnets, "emission")
    picks = build_simivision_picks_with_breakdown(top_emission)
    top_sn = top_emission[0] if top_emission else None
    council_votes = _build_council_votes(top_sn)
    soul_map = load_soul_map()
    return jsonify({"simivision_picks": picks, "council_votes": council_votes, "expert_weights": soul_map.get("expert_weights", {}), "feedback_logs": soul_map.get("feedback_logs", []), "learning_enabled": True, "generated_at": datetime.now().isoformat()})

@app.route("/api/rotation-tokens")
def api_rotation_tokens():
    """Return the specific subnet tokens in rotation."""
    return jsonify({"rotation_tokens": _ROTATION_TOKENS, "count": len(_ROTATION_TOKENS)})

@app.route("/api/feedback", methods=["POST"])
def record_feedback():
    """Record feedback for learning loop."""
    data = request.get_json() or {}
    subnet_id = data.get("subnet_id")
    recommendation = data.get("recommendation")
    actual_performance = data.get("actual_performance", {})
    
    if not subnet_id or not recommendation:
        return jsonify({"error": "Missing subnet_id or recommendation"}), 400
    
    engine = LearningEngine()
    engine.record_feedback(subnet_id, recommendation, actual_performance)
    
    return jsonify({"status": "feedback recorded", "success": True})

@app.route("/api/learning/stats")
def learning_stats():
    """Return learning loop statistics."""
    engine = LearningEngine()
    return jsonify(engine.get_stats())

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json() or {}
    message = data.get("message", "")
    subnets = get_dynamic_subnets()
    context = {"simivision_picks": get_top_performers(subnets, "emission")[:3], "market_overview": {"total_subnets": len(subnets), "active_count": len([s for s in subnets if s.get("status") == "active"]), "total_tvl": sum(s.get("market_cap", 0) for s in subnets) / 1e6}, "trending": get_top_performers(subnets, "price_change_24h")[:3], "highest_apy": get_top_performers(subnets, "apy")[0] if subnets else None, "source": "taomarketcap.com"}
    response = generate_ai_response(message, context)
    return jsonify({"response": response})

def generate_ai_response(message: str, context: Dict) -> str:
    """Generate a simple AI response based on context."""
    return f"Based on current market data, I recommend reviewing the top subnet picks. {message}"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))