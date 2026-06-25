import json
import logging
import math
import os
import sys
from datetime import datetime
from typing import Any, Dict, List
from flask import Flask, jsonify, make_response, request

# Add the current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetchers.taomarketcap import get_all_subnets, get_subnet_data
try:
    from data.learning_engine import LearningEngine
except ImportError:
    # Fallback if learning engine not available
    class LearningEngine:
        def get_stats(self):
            return {"expert_weights": {}, "total_records": 0}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

os.makedirs("data", exist_ok=True)

app = Flask(__name__)

_DEPLOY_TIMESTAMP = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
_APP_VERSION = "3.3.4"

_COOUNCIL_MEMBERS = [
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
    signal = macd_line * 0.8
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

def build_technical_indicators(sn: Dict) -> Dict:
    """Build technical indicators for a single subnet."""
    chg_24h = sn.get("price_change_24h", 0)
    chg_7d = sn.get("price_change_7d", 0)
    chg_30d = sn.get("price_change_30d", 0)
    price = sn.get("price", 1)
    if price <= 0:
        price = 1

    # Generate synthetic price history
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

    # Determine signals
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

# Root route - return basic HTML dashboard
@app.route("/")
def index():
    return """<!DOCTYPE html>
<html>
<head>
    <title>Subnet Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
               margin: 0; padding: 20px; background: #1a1a1a; color: #fff; }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { color: #00d4ff; }
        .status { background: #222; padding: 20px; border-radius: 8px; margin: 20px 0; }
        .status.ok { border-left: 4px solid #00ff88; }
        a { color: #00d4ff; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .api-link { display: block; margin: 10px 0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Subnet Dashboard</h1>
        <div class="status ok">
            <strong>✓ System Operational</strong>
        </div>
        <div class="status">
            <h3>Available Endpoints</h3>
            <a class="api-link" href="/health">/health</a>
            <a class="api-link" href="/api/subnets">/api/subnets</a>
            <a class="api-link" href="/api/simivision">/api/simivision</a>
            <a class="api-link" href="/api/mindmap/summary">/api/mindmap/summary</a>
            <a class="api-link" href="/api/rotation-tokens">/api/rotation-tokens</a>
            <a class="api-link" href="/api/learning/stats">/api/learning/stats</a>
        </div>
        <div class="status">
            <h3>Quick Links</h3>
            <a href="/api/simivision">View SimiVision Picks</a> | 
            <a href="/api/mindmap/summary">View Mindmap Summary</a> |
            <a href="/api/rotation-tokens">View Rotation Tokens</a>
        </div>
    </div>
</body>
</html>"""

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
    # Add technical indicators to each pick
    for pick in picks:
        netuid = pick.get("netuid")
        if netuid:
            sn_data = next((s for s in subnets if s.get("netuid") == netuid), {})
            pick["technical_indicators"] = build_technical_indicators(sn_data)
    
    engine = LearningEngine()
    stats = engine.get_stats()
    
    return jsonify({
        "data_source": "taomarketcap.com",
        "generated_at": datetime.now().isoformat(),
        "status": "operational",
        "picks": picks,
        "council": _build_council_votes(top_emission[0] if top_emission else {}),
        "learning_status": stats
    })

@app.route("/api/mindmap/summary")
def api_mindmap_summary():
    subnets = get_dynamic_subnets()
    top_emission = get_top_performers(subnets, "emission")
    picks = build_simivision_picks_with_breakdown(top_emission)
    top_sn = top_emission[0] if top_emission else {}
    council_votes = _build_council_votes(top_sn)
    
    tech_indicators = build_technical_indicators(top_sn) if top_sn else {}
    
    summary = build_mindmap_summary(top_sn, picks, council_votes, {}, tech_indicators)
    
    return jsonify(summary)

@app.route("/api/mindmap/feedback")
def api_mindmap_feedback():
    subnets = get_dynamic_subnets()
    top_emission = get_top_performers(subnets, "emission")
    picks = build_simivision_picks_with_breakdown(top_emission)
    top_sn = top_emission[0] if top_emission else {}
    council_votes = _build_council_votes(top_sn)
    tech_indicators = build_technical_indicators(top_sn) if top_sn else {}
    
    summary = build_mindmap_summary(top_sn, picks, council_votes, {}, tech_indicators)
    
    # Add rotation tokens info
    summary["rotation_tokens"] = _ROTATION_TOKENS
    
    return jsonify(summary)

@app.route("/api/rotation-tokens")
def api_rotation_tokens():
    return jsonify({"count": len(_ROTATION_TOKENS), "rotation_tokens": _ROTATION_TOKENS})

@app.route("/api/learning/stats")
def api_learning_stats():
    engine = LearningEngine()
    stats = engine.get_stats()
    return jsonify({
        "config": {
            "learning_rate": 0.1,
            "decay_factor": 0.99,
            "max_weight": 2.0,
            "min_weight": 0.1,
            "performance_window_days": 30
        },
        "expert_weights": stats.get("expert_weights", {}),
        "total_records": stats.get("total_records", 0),
        "last_updated": stats.get("last_updated")
    })

@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    data = request.get_json() or {}
    expert = data.get("expert")
    vote = data.get("vote")
    confidence = data.get("confidence", 50)
    rationale = data.get("rationale", "")
    
    engine = LearningEngine()
    engine.record_feedback(expert, vote, confidence, rationale)
    
    return jsonify({"status": "recorded", "expert": expert})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)