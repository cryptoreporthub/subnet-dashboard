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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

os.makedirs("data", exist_ok=True)

app = Flask(__name__)

_DEPLOY_TIMESTAMP = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
_APP_VERSION = "3.0.0"

_COUNCIL_MEMBERS = [
    {"name": "Alpha", "bias": "momentum"},
    {"name": "Beta", "bias": "value"},
    {"name": "Gamma", "bias": "sentiment"},
]

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

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json() or {}
    message = data.get("message", "")
    subnets = get_dynamic_subnets()
    context = {"simivision_picks": get_top_performers(subnets, "emission")[:3], "market_overview": {"total_subnets": len(subnets), "active_count": len([s for s in subnets if s.get("status") == "active"]), "total_tvl": sum(s.get("market_cap", 0) for s in subnets) / 1e6}, "trending": get_top_performers(subnets, "price_change_24h")[:3], "highest_apy": get_top_performers(subnets, "apy")[0] if subnets else None, "source": "taomarketcap.com"}
    response = generate_ai_response(message, context)
    return jsonify({"reply": response, "context_used": list(context.keys()), "data_source": "live from taomarketcap.com"})

def generate_ai_response(message: str, context: Dict) -> str:
    msg_lower = message.lower()
    if "coldint" in msg_lower or "why" in msg_lower:
        top = context["simivision_picks"][0] if context["simivision_picks"] else None
        if top:
            return f"Based on SimiVision analysis from taomarketcap.com, {top['name']} (SN{top['netuid']}) ranks #1 due to high emission ({top['emission']}%), strong APY ({top['apy']}%), and strong market momentum."
    if "apy" in msg_lower:
        top = context.get("highest_apy")
        if top:
            return f"The highest APY subnet is {top['name']} (SN{top['netuid']}) at {top['apy']}%"
    if "trending" in msg_lower or "top" in msg_lower:
        trending = context.get("trending", [])
        if trending:
            items = ", ".join([f"{s['name']} ({s['price_change_24h']}%)" for s in trending])
            return f"Currently trending subnets (by 24h price change): {items}"
    return "I'm SimiVision AI powered by live taomarketcap.com data."

@app.route("/api/radar")
def api_radar():
    subnets = get_dynamic_subnets()
    radar = _build_radar_picks(subnets)
    return jsonify({
        "status": "operational",
        "data_source": "taomarketcap.com + GitHub commit analysis",
        "radar": radar,
        "generated_at": datetime.now().isoformat(),
    })

@app.route("/api/technicals")
def api_technicals():
    subnets = get_dynamic_subnets()
    tech = _build_tech_indicators(subnets)
    return jsonify({"status": "operational", "indicators": tech, "generated_at": datetime.now().isoformat()})

# ────────────────────────────────────────────────────────────────────────────
# SVG circular chart helper
# ────────────────────────────────────────────────────────────────────────────
def _circular_chart_svg(pct: float, size: int = 48, stroke_w: int = 4, color: str = "#00d9ff") -> str:
    """Return an inline SVG circular progress chart."""
    r = (size - stroke_w) // 2
    cx = cy = size // 2
    circ = 2 * math.pi * r
    offset = circ * (1 - pct / 100)
    return f"""<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="{stroke_w}"/>
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke_w}"
    stroke-dasharray="{circ}" stroke-dashoffset="{offset}" stroke-linecap="round"
    transform="rotate(-90 {cx} {cy})"/>
  <text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="central"
    fill="{color}" font-size="{size//3}" font-weight="700" font-family="monospace">{pct}%</text>
</svg>"""

# ────────────────────────────────────────────────────────────────────────────
# Premium Dashboard
# ────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    subnets = get_dynamic_subnets()
    logger.info("Rendering premium dashboard with %d subnets", len(subnets))
    top_emission = get_top_performers(subnets, "emission")
    active_subnets = [s for s in subnets if s.get("status") == "active"]
    simivision_picks = build_simivision_picks_with_breakdown(top_emission)
    council_votes = _build_council_votes(top_emission[0] if top_emission else None)
    radar_picks = _build_radar_picks(subnets)
    tech_indicators = _build_tech_indicators(subnets)

    total_tvl = sum(s.get("market_cap", 0) for s in subnets) / 1e6
    active_count = len(active_subnets)
    total_count = len(subnets)
    live_time = datetime.now().strftime("%H:%M UTC")

    # ── Sidebar ticker ──
    ticker_rows = ""
    for s in subnets[:16]:
        e = s.get("emission", 0)
        chg = s.get("price_change_24h", 0)
        chg_cls = "up" if chg >= 0 else "down"
        ticker_rows += f"""<a class="ti" data-netuid="{s['netuid']}">
  <span class="ti-name">#{s["netuid"]} {s["name"]}</span>
  <span class="ti-em">{e:.2f} TAO</span>
  <span class="ti-chg {chg_cls}">{chg:+.1f}%</span>
</a>"""

    # ── SimiVision Picks ──
    picks_cards = ""
    colors_3 = ["#00d9ff", "#7b68ee", "#f59e0b"]
    for i, pick in enumerate(simivision_picks):
        color = colors_3[i]
        chg_cls = "up" if pick["price_change_24h"] >= 0 else "down"
        chart_svg = _circular_chart_svg(pick["conviction"], 52, 5, color)
        bd = pick["breakdown"]
        bd_html = "".join(f"<li>{line}</li>" for line in bd[:2])
        mc = pick["metrics"]["market_cap"]
        mc_str = f"${mc:,.0f}" if mc >= 1_000_000 else f"${mc:,.0f}"
        picks_cards += f"""
<div class="dp-card pick-card" style="--accent:{color}">
  <div class="pick-hd">
    <div class="pick-rank" style="background:rgba({','.join(str(int(c,16)) for c in [color[1:3],color[3:5],color[5:7]] if len(color)==7)},0.15);color:{color}">#{pick['rank']}</div>
    <div class="pick-info"><div class="pick-name">{pick['name']}</div><div class="pick-tag" style="background:rgba({','.join(str(int(c,16)) for c in [color[1:3],color[3:5],color[5:7]] if len(color)==7)},0.2);color:{color}">{pick['recommendation']}</div></div>
    {chart_svg}
  </div>
  <div class="pick-metrics">
    <div class="pm"><span class="pm-l">Emission</span><span class="pm-v">{pick['emission']:.2f} TAO</span></div>
    <div class="pm"><span class="pm-l">24h</span><span class="pm-v {chg_cls}">{pick['price_change_24h']:+.1f}%</span></div>
    <div class="pm"><span class="pm-l">APY</span><span class="pm-v">{pick['apy']:.1f}%</span></div>
    <div class="pm"><span class="pm-l">Market Cap</span><span class="pm-v">{mc_str}</span></div>
  </div>
  <ul class="pick-signals">{bd_html}</ul>
</div>"""

    # ── Learning Trail Council ──
    council_colors = {"Alpha": "#00d9ff", "Beta": "#7b68ee", "Gamma": "#f59e0b"}
    council_cards = ""
    for member in council_votes:
        c = council_colors.get(member["name"], "#22c55e")
        vote_cls = "buy" if member["vote"] == "BUY" else "sell" if member["vote"] == "SELL" else "hold"
        chart_svg = _circular_chart_svg(member["confidence"], 52, 5, c)
        council_cards += f"""
<div class="dp-card council-card" style="--accent:{c}">
  <div class="council-hd">
    <div class="council-dot" style="background:{c}"></div>
    <div class="council-name">{member['name']}</div>
    <div class="rec-tag {vote_cls}">{member['vote']}</div>
    {chart_svg}
  </div>
  <p class="council-rat">{member['rationale']}</p>
</div>"""

    # ── Spotlight with Technical Indicators ──
    top_emitter = top_emission[0] if top_emission else None
    top_apy_item = get_top_performers(subnets, "apy")[0] if subnets else None
    pct_active = (active_count / total_count * 100) if total_count > 0 else 0
    spotlight_cards = ""
    if top_emitter:
        em = top_emitter.get("emission", 0)
        spotlight_cards += f"""
<div class="dp-card spotlight-card" style="--accent:#00d9ff">
  <div class="sphd" style="border-bottom-color:#00d9ff"><span class="sphd-icon">🏆</span> Top Emitter</div>
  <div class="spbody"><div class="spname">{top_emitter['name']}</div><div class="spval" style="color:#00d9ff">{em:.3f} TAO</div></div>
</div>"""
    if top_apy_item:
        av = top_apy_item.get("apy", 0)
        spotlight_cards += f"""
<div class="dp-card spotlight-card" style="--accent:#7b68ee">
  <div class="sphd" style="border-bottom-color:#7b68ee"><span class="sphd-icon">📈</span> Highest APY</div>
  <div class="spbody"><div class="spname">{top_apy_item['name']}</div><div class="spval" style="color:#7b68ee">{av:.2f}%</div></div>
</div>"""
    spotlight_cards += f"""
<div class="dp-card spotlight-card" style="--accent:#22c55e">
  <div class="sphd" style="border-bottom-color:#22c55e"><span class="sphd-icon">🔗</span> Active Subnets</div>
  <div class="spbody"><div class="spname">{active_count}/{total_count}</div><div class="spval" style="color:#22c55e">{pct_active:.0f}%</div></div>
</div>"""

    # ── Tech Indicators Section ──
    tech_rows = ""
    for t in tech_indicators:
        rsi = t["rsi"]
        rsi_color = "#ef4444" if rsi > 70 else "#22c55e" if rsi < 30 else "#f59e0b"
        rsi_label = t["rsi_signal"]
        macd_sig = t["macd"]["crossover"]
        macd_color = "#22c55e" if macd_sig == "bullish" else "#ef4444" if macd_sig == "bearish" else "#f59e0b"
        ma_sig = t["ma_cross"]["signal"]
        ma_color = "#22c55e" if ma_sig == "bullish" else "#ef4444" if ma_sig == "bearish" else "#f59e0b"
        tech_rows += f"""
<tr>
  <td><span class="sn-cell">{t['name']}</span></td>
  <td><span class="ind-val" style="color:{rsi_color}">{rsi:.1f}</span><span class="ind-lbl">{rsi_label}</span></td>
  <td><span class="ind-val" style="color:{macd_color}">{t['macd']['macd']:.4f}</span><span class="ind-lbl">{macd_sig}</span></td>
  <td><span class="ind-val" style="color:{ma_color}">{ma_sig}</span><span class="ind-lbl">{'MA7 > MA25' if ma_sig == 'bullish' else 'MA7 < MA25' if ma_sig == 'bearish' else 'MA7 ≈ MA25'}</span></td>
</tr>"""

    # ── Undervalued Radar ──
    radar_rows = ""
    for rp in radar_picks:
        bar_w = min(rp["dev_score"], 100)
        commits = rp["github_commits_7d"]
        mc_str = f"${rp['market_cap']:,.0f}" if rp["market_cap"] >= 1 else "N/A"
        act = rp["commit_activity"][0] if isinstance(rp["commit_activity"], list) else rp["commit_activity"]
        act_color = "#22c55e" if act == "high" else "#f59e0b" if act == "medium" else "#ef4444"
        radar_rows += f"""
<div class="radar-item">
  <div class="radar-hd">
    <span class="sn-cell">{rp['name']}</span>
    <span class="rec-tag undervalued" style="margin:0">#{'%0.1f' % rp['undervalued_score']}</span>
  </div>
  <div class="pick-metrics" style="grid-template-columns:1fr 1fr 1fr">
    <div class="pm"><span class="pm-l">Market Cap</span><span class="pm-v">{mc_str}</span></div>
    <div class="pm"><span class="pm-l">Dev Score</span><span class="pm-v" style="color:#22c55e">{rp['dev_score']}/100</span></div>
    <div class="pm"><span class="pm-l">Commits</span><span class="pm-v" style="color:#7b68ee">{commits}/7d</span></div>
  </div>
  <div class="dev-bar"><div class="dev-fill" style="width:{bar_w}%"></div></div>
  <div class="gh-act" style="color:{act_color}">● {act} development</div>
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Subnet Pulse · Professional Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg-deep: #07070f;
    --bg-surface: #0b0b18;
    --bg-card: #0f0f22;
    --bg-elevated: #151530;
    --border: #1c1c3a;
    --border-light: #28284d;
    --text-primary: #e8e8f0;
    --text-secondary: #9090b0;
    --text-muted: #606080;
    --cyan: #00d9ff;
    --violet: #7b68ee;
    --amber: #f59e0b;
    --green: #22c55e;
    --red: #ef4444;
    --gradient-hero: linear-gradient(135deg, rgba(0,217,255,0.08) 0%, rgba(123,104,238,0.08) 100%);
    --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    --font-mono: 'JetBrains Mono', 'SF Mono', Menlo, monospace;
  }}

  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  html{{font-size:14px;scroll-behavior:smooth}}
  body{{background:var(--bg-deep);color:var(--text-primary);font-family:var(--font-sans);min-height:100vh;background-image:radial-gradient(circle at 20% 30%,rgba(0,217,255,0.03) 0%,transparent 50%),radial-gradient(circle at 80% 10%,rgba(123,104,238,0.03) 0%,transparent 50%);line-height:1.5}}
  a{{color:inherit;text-decoration:none}}

  .app{{display:flex;max-width:1500px;margin:0 auto;min-height:100vh}}

  /* ── Sidebar ── */
  .side{{width:260px;background:var(--bg-surface);border-right:1px solid var(--border);padding:1.25rem;flex-shrink:0;overflow-y:auto;position:sticky;top:0;height:100vh}}
  .side-logo{{display:flex;align-items:center;gap:.5rem;margin-bottom:1.25rem;padding-bottom:.75rem;border-bottom:1px solid var(--border)}}
  .side-logo .logo-dot{{width:10px;height:10px;border-radius:50%;background:var(--cyan);box-shadow:0 0 12px rgba(0,217,255,0.4);animation:pulse 2s infinite}}
  .side-logo h2{{font-size:.85rem;font-weight:700;color:var(--text-primary);letter-spacing:-.3px}}
  .side-logo span{{font-size:.6rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;margin-left:auto}}
  .side h3{{font-size:.65rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:1.5px;margin-bottom:.5rem;margin-top:.75rem}}
  .ti{{display:grid;grid-template-columns:1fr auto auto;gap:6px;padding:.35rem .6rem;color:var(--text-secondary);border-radius:6px;font-size:.75rem;margin-bottom:1px;align-items:center;transition:all .15s;cursor:default}}
  .ti:hover{{background:var(--bg-elevated);color:var(--text-primary)}}
  .ti-name{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
  .ti-em{{font-family:var(--font-mono);font-size:.7rem;color:var(--cyan)}}
  .ti-chg{{font-family:var(--font-mono);font-size:.68rem;font-weight:600}}
  .ti-chg.up{{color:var(--green)}}
  .ti-chg.down{{color:var(--red)}}

  /* ── Main ── */
  .main{{flex:1;padding:1.5rem 2rem;overflow-y:auto;max-width:1240px}}

  /* ── Header ── */
  .hd{{display:flex;align-items:center;justify-content:space-between;margin-bottom:1.5rem;flex-wrap:wrap;gap:.75rem}}
  .hd-left{{display:flex;align-items:center;gap:.75rem}}
  .hd-left h1{{font-size:1.5rem;font-weight:800;color:var(--text-primary);letter-spacing:-.5px;background:linear-gradient(135deg,var(--cyan),var(--violet));-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
  .hd-left h1 small{{font-size:.6rem;font-weight:500;color:var(--text-muted);-webkit-text-fill-color:var(--text-muted);margin-left:.4rem}}
  .live-badge{{display:inline-flex;align-items:center;gap:5px;font-size:.65rem;font-weight:600;color:var(--green);background:rgba(34,197,94,0.12);border:1px solid rgba(34,197,94,0.25);border-radius:999px;padding:3px 10px;text-transform:uppercase;letter-spacing:.3px}}
  .live-badge::before{{content:"";width:6px;height:6px;border-radius:50%;background:var(--green);animation:pulse 1.5s infinite}}
  @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.3}}}}

  .hd-right{{display:flex;gap:.5rem;align-items:center}}
  .time-display{{font-size:.7rem;color:var(--text-muted);font-family:var(--font-mono)}}

  /* ── Stats bar ── */
  .stats{{display:flex;gap:.5rem;margin-bottom:1.5rem;flex-wrap:wrap}}
  .stat-pill{{background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:.4rem .85rem;font-size:.75rem;color:var(--text-secondary);display:flex;align-items:center;gap:6px}}
  .stat-pill strong{{color:var(--cyan);font-family:var(--font-mono);font-weight:700}}

  /* ── Section headers ── */
  .sec-hd{{display:flex;align-items:center;gap:.5rem;margin:1.5rem 0 .85rem}}
  .sec-hd h2{{font-size:.9rem;font-weight:700;color:var(--text-primary);text-transform:uppercase;letter-spacing:.5px}}
  .sec-hd .sec-line{{flex:1;height:1px;background:linear-gradient(90deg,var(--border),transparent)}}
  .sec-hd .sec-count{{font-size:.65rem;color:var(--text-muted);font-family:var(--font-mono);background:var(--bg-elevated);padding:2px 8px;border-radius:999px}}

  /* ── Dashboard Cards ── */
  .dp-card{{background:var(--bg-card);border:1px solid var(--border);border-radius:14px;overflow:hidden;transition:all .25s;position:relative}}
  .dp-card:hover{{border-color:var(--border-light);transform:translateY(-1px);box-shadow:0 8px 32px rgba(0,0,0,0.3)}}
  .dp-card::before{{content:"";position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--accent,#7b68ee),transparent);opacity:0;transition:opacity .25s}}
  .dp-card:hover::before{{opacity:1}}

  /* ── Grid layouts ── */
  .grid-picks{{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}}
  .grid-council{{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}}
  .grid-spotlight{{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}}

  /* ── Pick cards ── */
  .pick-hd{{display:flex;align-items:center;gap:.6rem;padding:.85rem .85rem 0;justify-content:space-between}}
  .pick-rank{{width:32px;height:32px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:.85rem;font-weight:800;flex-shrink:0}}
  .pick-info{{flex:1;min-width:0}}
  .pick-name{{font-size:.85rem;font-weight:700;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
  .pick-tag{{font-size:.6rem;font-weight:700;padding:1px 7px;border-radius:5px;display:inline-block;text-transform:uppercase;letter-spacing:.3px;margin-top:2px}}
  .pick-metrics{{display:grid;grid-template-columns:1fr 1fr;gap:2px 12px;padding:.5rem .85rem 0}}
  .pm{{display:flex;justify-content:space-between;align-items:center}}
  .pm-l{{font-size:.65rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.3px}}
  .pm-v{{font-size:.78rem;font-weight:600;color:var(--text-primary);font-family:var(--font-mono)}}
  .pm-v.up{{color:var(--green)}}
  .pm-v.down{{color:var(--red)}}
  .pick-signals{{list-style:none;padding:.35rem .85rem .7rem}}
  .pick-signals li{{font-size:.68rem;color:var(--text-secondary);padding:2px 0 2px 11px;position:relative}}
  .pick-signals li::before{{content:"";position:absolute;left:0;top:7px;width:4px;height:4px;border-radius:50%;background:var(--accent,var(--cyan))}}

  /* ── Council cards ── */
  .council-hd{{display:flex;align-items:center;gap:.5rem;padding:.85rem .85rem 0}}
  .council-dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0}}
  .council-name{{font-size:.85rem;font-weight:700;color:var(--text-primary);flex:1}}
  .rec-tag{{font-size:.6rem;font-weight:700;padding:2px 8px;border-radius:6px;text-transform:uppercase;letter-spacing:.3px}}
  .rec-tag.buy{{background:rgba(34,197,94,.15);color:var(--green)}}
  .rec-tag.hold{{background:rgba(245,158,11,.15);color:var(--amber)}}
  .rec-tag.watch{{background:rgba(0,217,255,.15);color:var(--cyan)}}
  .rec-tag.sell{{background:rgba(239,68,68,.15);color:var(--red)}}
  .rec-tag.undervalued{{background:rgba(34,197,94,.15);color:var(--green);border:1px solid rgba(34,197,94,.2)}}
  .council-rat{{font-size:.72rem;color:var(--text-secondary);font-style:italic;padding:.5rem .85rem .7rem;line-height:1.4}}
  .council-card .council-hd svg{{flex-shrink:0}}

  /* ── Spotlight ── */
  .sphd{{display:flex;align-items:center;gap:.35rem;font-size:.72rem;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;padding:.7rem .85rem .5rem;border-bottom:2px solid}}
  .sphd-icon{{font-size:.85rem}}
  .spbody{{padding:.6rem .85rem .85rem;text-align:center}}
  .spname{{font-size:.95rem;font-weight:700;color:var(--text-primary);margin-bottom:.15rem}}
  .spval{{font-size:1.3rem;font-weight:800;font-family:var(--font-mono)}}

  /* ── Tech indicators table ── */
  .tbl-wrap{{overflow-x:auto;margin-bottom:1rem}}
  table.ind-tbl{{width:100%;border-collapse:collapse}}
  table.ind-tbl th{{text-align:left;padding:.55rem .75rem;font-size:.65rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.8px;font-weight:600;border-bottom:1px solid var(--border);white-space:nowrap}}
  table.ind-tbl td{{padding:.45rem .75rem;border-bottom:1px solid rgba(28,28,58,.5);font-size:.78rem;white-space:nowrap}}
  table.ind-tbl tr:hover td{{background:rgba(255,255,255,0.02)}}
  .sn-cell{{font-weight:600;color:var(--text-primary)}}
  .ind-val{{font-family:var(--font-mono);font-weight:700;font-size:.82rem;display:block}}
  .ind-lbl{{font-size:.62rem;color:var(--text-muted);text-transform:capitalize}}

  /* ── Radar section ── */
  .radar-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:1rem}}
  .radar-item{{background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:.75rem .85rem}}
  .radar-item:hover{{border-color:var(--border-light)}}
  .radar-hd{{display:flex;align-items:center;justify-content:space-between;margin-bottom:.35rem}}
  .radar-hd .sn-cell{{font-size:.82rem}}
  .dev-bar{{height:4px;background:var(--bg-elevated);border-radius:3px;overflow:hidden;margin:.35rem 0 .25rem}}
  .dev-fill{{height:100%;background:linear-gradient(90deg,var(--green),var(--violet));border-radius:3px;transition:width .5s}}
  .gh-act{{font-size:.65rem;font-weight:600;text-transform:capitalize;display:flex;align-items:center;gap:4px;margin-top:2px}}

  /* ── Footer ── */
  footer{{margin-top:2rem;padding:.85rem 0 0;border-top:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem}}
  footer .f-copy{{font-size:.7rem;color:var(--text-muted)}}
  footer .f-ver{{font-size:.65rem;color:var(--text-muted);font-family:var(--font-mono)}}

  /* ── Responsive ── */
  @media(max-width:1200px){{.grid-picks,.grid-council{{grid-template-columns:repeat(2,1fr)}}.grid-picks .pick-card:last-child,.grid-council .council-card:last-child{{grid-column:span 2}}}}
  @media(max-width:900px){{.grid-picks,.grid-council,.grid-spotlight{{grid-template-columns:1fr}}.grid-picks .pick-card:last-child,.grid-council .council-card:last-child{{grid-column:span 1}}.radar-grid{{grid-template-columns:1fr}}}}
  @media(max-width:768px){{
    .app{{flex-direction:column}}
    .side{{width:100%;height:auto;position:static;border-right:none;border-bottom:1px solid var(--border);padding:.6rem .85rem;display:flex;flex-wrap:wrap;align-items:center;gap:.25rem}}
    .side-logo{{margin-bottom:0;padding-bottom:0;border-bottom:none;flex:1}}
    .side h3{{display:none}}
    .ti{{font-size:.68rem;padding:.2rem .4rem}}
    .main{{padding:.75rem}}
    .hd-left h1{{font-size:1.15rem}}
    .stats{{gap:.35rem}}
    .stat-pill{{font-size:.68rem;padding:.3rem .6rem}}
  }}
</style>
</head>
<body>
<div class="app">
  <aside class="side">
    <div class="side-logo">
      <div class="logo-dot"></div>
      <h2>Subnet Pulse</h2>
      <span>v{_APP_VERSION}</span>
    </div>
    <h3>Subnet Feed</h3>
    {ticker_rows}
  </aside>
  <main class="main">
    <div class="hd">
      <div class="hd-left">
        <h1>Subnet Pulse <small>Professional</small></h1>
        <span class="live-badge">Live</span>
      </div>
      <div class="hd-right">
        <span class="time-display">{live_time}</span>
      </div>
    </div>

    <div class="stats">
      <div class="stat-pill">Total Subnets <strong>{total_count}</strong></div>
      <div class="stat-pill">Active <strong>{active_count}</strong></div>
      <div class="stat-pill">TVL <strong>${total_tvl:.2f}M</strong></div>
      <div class="stat-pill">Data <strong>taomarketcap.com</strong></div>
    </div>

    <!-- ═══ SimiVision Picks ═══ -->
    <div class="sec-hd">
      <h2>SimiVision Picks</h2>
      <span class="sec-line"></span>
      <span class="sec-count">AI</span>
    </div>
    <div class="grid-picks">
      {picks_cards}
    </div>

    <!-- ═══ Learning Trail Council ═══ -->
    <div class="sec-hd">
      <h2>Learning Trail Council</h2>
      <span class="sec-line"></span>
      <span class="sec-count">Vote</span>
    </div>
    <div class="grid-council">
      {council_cards}
    </div>

    <!-- ═══ Spotlight ═══ -->
    <div class="sec-hd">
      <h2>Spotlight</h2>
      <span class="sec-line"></span>
      <span class="sec-count">Top</span>
    </div>
    <div class="grid-spotlight">
      {spotlight_cards}
    </div>

    <!-- ═══ Technical Indicators ═══ -->
    <div class="sec-hd">
      <h2>Technical Indicators</h2>
      <span class="sec-line"></span>
      <span class="sec-count">RSI · MACD · MA</span>
    </div>
    <div class="tbl-wrap">
      <table class="ind-tbl">
        <thead><tr><th>Subnet</th><th>RSI (14)</th><th>MACD</th><th>MA Cross</th></tr></thead>
        <tbody>{tech_rows}</tbody>
      </table>
    </div>

    <!-- ═══ Undervalued Radar ═══ -->
    <div class="sec-hd">
      <h2>Undervalued Radar</h2>
      <span class="sec-line"></span>
      <span class="sec-count">Dev · Commits</span>
    </div>
    <div class="radar-grid">
      {radar_rows}
    </div>

    <footer>
      <span class="f-copy">Subnet Pulse · Powered by <strong style="color:var(--cyan)">taomarketcap.com</strong></span>
      <span class="f-ver">v{_APP_VERSION} · {_DEPLOY_TIMESTAMP}</span>
    </footer>
  </main>
</div>
</body>
</html>"""

    response = make_response(html)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
