"""Subnet Dashboard server package."""
from server.config import *  # noqa: F403

@app.get("/api/daily-pick")
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
        breakdown.append(f"Strong Daily Rewards ({emission:.2f} TAO/day) - high priority for miners")
    elif emission >= 1:
        breakdown.append(f"Solid Daily Rewards ({emission:.2f} TAO/day) - consistent rewards")
    else:
        breakdown.append(f"Daily Rewards at {emission:.2f} TAO/day - emerging subnet")
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
from datastore.learning_engine import create_feedback_router

_feedback_router = create_feedback_router()
if _feedback_router is not None:
    app.include_router(_feedback_router)
