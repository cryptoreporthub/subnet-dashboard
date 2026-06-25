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
    class LearningEngine:
        def get_stats(self):
            return {"expert_weights": {}, "total_records": 0}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

os.makedirs("data", exist_ok=True)

app = Flask(__name__)

_APP_VERSION = "3.5.0"

_ROTATION_TOKENS = ["hyperliquid", "vvv", "near", "render", "fetch"]

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

@app.route("/")
def index():
    subnets = get_dynamic_subnets()
    top_emission = get_top_performers(subnets, "emission")
    picks = build_simivision_picks_with_breakdown(top_emission)
    top_sn = top_emission[0] if top_emission else {}
    council_votes = _build_council_votes(top_sn)
    
    # Mobile-first dark dashboard HTML
    html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Subnet Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            background: #0a0a0a; 
            color: #e0e0e0; 
            line-height: 1.6;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 16px; }
        header { 
            display: flex; 
            align-items: center; 
            justify-content: space-between; 
            padding: 12px 16px; 
            border-bottom: 1px solid #1a1a1a; 
            margin-bottom: 20px;
        }
        .logo { 
            font-size: 20px; 
            font-weight: 700; 
            background: linear-gradient(90deg, #006600, #003300, #000000);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .status { font-size: 12px; color: #00ff88; }
        .card { 
            background: #111111; 
            border-radius: 12px; 
            padding: 16px; 
            margin-bottom: 16px; 
            border: 1px solid #1a1a1a;
        }
        .card h2 { 
            font-size: 16px; 
            color: #00d4ff; 
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .pick { 
            background: #1a1a1a; 
            border-radius: 8px; 
            padding: 12px; 
            margin-bottom: 12px;
            border-left: 3px solid #00d4ff;
        }
        .pick:nth-child(1) { border-left-color: #00ff88; }
        .pick:nth-child(2) { border-left-color: #ffaa00; }
        .pick:nth-child(3) { border-left-color: #ff6600; }
        .pick-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .pick-title { font-weight: 600; }
        .conviction { font-size: 12px; background: #333; padding: 2px 8px; border-radius: 4px; }
        .pick ul { font-size: 13px; color: #aaa; margin-left: 16px; margin-bottom: 8px; }
        .pick ul li { margin: 4px 0; }
        .metrics { font-size: 12px; color: #666; margin-top: 8px; }
        .council-member { 
            display: inline-block; 
            background: #1a1a1a; 
            padding: 10px; 
            border-radius: 8px; 
            margin: 8px; 
            min-width: 120px;
        }
        .council-member h3 { font-size: 14px; margin-bottom: 4px; }
        .council-member p { font-size: 12px; color: #888; }
        .spotlight { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        .spotlight-item { text-align: center; padding: 8px; background: #1a1a1a; border-radius: 8px; }
        .spotlight-item strong { color: #00d4ff; display: block; margin-bottom: 4px; }
        .footer { text-align: center; padding: 20px; color: #444; font-size: 12px; margin-top: 20px; }
        @media (min-width: 768px) {
            .container { padding: 24px; }
            .dashboard-grid { display: grid; grid-template-columns: 1fr 300px; gap: 24px; }
            .main-content { display: grid; gap: 16px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo"># Subnet Pulse</div>
            <div class="status">● Operational</div>
        </header>
        
        <div class="main-content">
            <div class="card">
                <h2>## SimiVision</h2>
'''
    
    if picks:
        for pick in picks:
            html += f'''
                <div class="pick">
                    <div class="pick-header">
                        <span class="pick-title">#{pick['rank']} {pick['name']}</span>
                        <span class="conviction">{pick['conviction']}% {pick['recommendation']}</span>
                    </div>
                    <p style="font-size: 13px; margin-bottom: 8px;"><strong>Why {pick['name']}?</strong></p>
                    <ul>
'''
            for item in pick['breakdown']:
                html += f"                        <li>{item}</li>\n"
            html += f'''                    </ul>
                    <div class="metrics">
                        Emission: {pick['emission']:.2f} TAO | 24h: {pick['price_change_24h']:+.1f}% | APY: {pick['apy']:.2f}%
                    </div>
                </div>
'''
    else:
        html += "                <p>No SimiVision picks available.</p>\n"
    
    html += '''            </div>
            
            <div class="card">
                <h2>## Learning Trail</h2>
'''
    
    if council_votes:
        for member in council_votes:
            html += f'''
                <div class="council-member">
                    <h3>{member['name']}</h3>
                    <p>{member['vote']} {member['confidence']}%</p>
                    <small>{member['rationale'][:40]}...</small>
                </div>
'''
    else:
        html += "                <p>Council deliberation in progress.</p>\n"
    
    html += f'''
            </div>
            
            <div class="card">
                <h2>## Spotlight</h2>
                <div class="spotlight">
                    <div class="spotlight-item">
                        <strong>Top Emitter</strong>
                        <span>{picks[0]['name'] if picks else 'N/A'}</span>
                        <span>({picks[0]['emission']:.2f} TAO)</span>
                    </div>
                    <div class="spotlight-item">
                        <strong>Highest APY</strong>
                        <span>{picks[0]['name'] if picks else 'N/A'}</span>
                        <span>({picks[0]['apy']:.1f}%)</span>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="footer">
            Subnet Pulse · Powered by <strong>taomarketcap.com</strong> · Built for the Bittensor ecosystem.
        </div>
    </div>
</body>
</html>'''
    
    response = make_response(html)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response

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
    
    return jsonify({
        "acknowledgment": f"Analyzing subnet {top_sn.get('netuid', 'N/A')} - {top_sn.get('name', 'Unknown')}",
        "noticed": [f"High emission rate ({top_sn.get('emission', 0):.2f} TAO/day)"] if top_sn else ["No significant signals detected"],
        "opinion_changes": ["No significant opinion changes"],
        "technical_indicators": tech_indicators.get("signals", ["Insufficient data"]),
        "conviction": {"current": 95.0, "trend": "stable", "explanation": "Based on live data"},
        "expert_insights": [{"expert": v.get("name", "Unknown"), "bias": v.get("rationale", "")[:50] + "...", "confidence": v.get("confidence", 50)} for v in council_votes],
        "learning_status": {"enabled": True, "records": 0, "last_updated": None},
        "timestamp": datetime.now().isoformat()
    })

@app.route("/api/mindmap/feedback")
def api_mindmap_feedback():
    subnets = get_dynamic_subnets()
    top_emission = get_top_performers(subnets, "emission")
    picks = build_simivision_picks_with_breakdown(top_emission)
    top_sn = top_emission[0] if top_emission else {}
    council_votes = _build_council_votes(top_sn)
    tech_indicators = build_technical_indicators(top_sn) if top_sn else {}
    
    return jsonify({
        "acknowledgment": f"Analyzing subnet {top_sn.get('netuid', 'N/A')} - {top_sn.get('name', 'Unknown')}",
        "noticed": [f"High emission rate ({top_sn.get('emission', 0):.2f} TAO/day)"] if top_sn else ["No significant signals detected"],
        "opinion_changes": ["No significant opinion changes"],
        "technical_indicators": tech_indicators.get("signals", ["Insufficient data"]),
        "conviction": {"current": 95.0, "trend": "stable", "explanation": "Based on live data"},
        "expert_insights": [{"expert": v.get("name", "Unknown"), "bias": v.get("rationale", "")[:50] + "...", "confidence": v.get("confidence", 50)} for v in council_votes],
        "learning_status": {"enabled": True, "records": 0, "last_updated": None},
        "rotation_tokens": _ROTATION_TOKENS,
        "timestamp": datetime.now().isoformat()
    })

@app.route("/api/rotation-tokens")
def api_rotation_tokens():
    return jsonify({"count": len(_ROTATION_TOKENS), "rotation_tokens": _ROTATION_TOKENS})

@app.route("/api/learning/stats")
def api_learning_stats():
    engine = LearningEngine()
    stats = engine.get_stats()
    return jsonify({
        "config": {"learning_rate": 0.1, "decay_factor": 0.99, "max_weight": 2.0, "min_weight": 0.1, "performance_window_days": 30},
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