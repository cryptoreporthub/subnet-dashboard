"""
Subnet state vector builder.

Provides a reusable, serializable state vector for a single subnet plus scoring
helpers used by the Selector's top-pick engine.
"""

import json as _json
import math as _math
import os as _os
import uuid as _uuid
from datetime import datetime as _dt, timedelta as _td
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
_PRICE_CACHE_PATH = _os.path.join("data", "price_cache.json")
_REGISTRY_PATH = _os.path.join("config", "registry.json")
_SIGNAL_TYPES_PATH = _os.path.join("config", "signal_types.json")


# ---------------------------------------------------------------------------
# Signal type metadata (mirrors server.py defaults)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Price history helper
# ---------------------------------------------------------------------------
def _load_price_cache() -> Dict[str, Any]:
    try:
        with open(_PRICE_CACHE_PATH, "r") as f:
            return _json.load(f)
    except Exception:
        return {}


def _empty_price_history() -> Dict[str, Any]:
    return {
        "closes": [],
        "highs": [],
        "lows": [],
        "volumes": [],
        "timestamps": [],
        "source": "unavailable",
    }


def _get_price_history(netuid: Any, sn: Dict[str, Any]) -> Dict[str, Any]:
    """Return {closes, highs, lows, volumes, timestamps, source} for a subnet."""
    closes: List[float] = []
    highs: List[float] = []
    lows: List[float] = []
    volumes: List[float] = []
    timestamps: List[str] = []
    source = "unavailable"

    cache = _load_price_cache()
    if isinstance(netuid, dict):
        netuid = netuid.get("id") or netuid.get("netuid") or netuid.get("subnet") or 0
    try:
        netuid = int(netuid)
    except (TypeError, ValueError):
        netuid = str(netuid)
    raw = cache.get(str(netuid)) or cache.get(int(netuid) if str(netuid).isdigit() else netuid)
    if raw and isinstance(raw, dict):
        source = raw.get("source", "cached")
        if source == "synthetic":
            return _empty_price_history()
        candles = raw.get("candles") or []
        if candles:
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
        return _empty_price_history()

    return {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
        "timestamps": timestamps,
        "source": source,
    }


# ---------------------------------------------------------------------------
# Technical indicator helpers
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
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = diff if diff >= 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_gain == 0 and avg_loss == 0:
        return 50.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


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
        return 50.0
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


def _compute_ma_cross(prices: List[float]) -> Dict[str, Any]:
    if len(prices) < 25:
        return {"ma7": 0, "ma25": 0, "signal": "neutral"}
    ma7 = sum(prices[-7:]) / 7
    ma25_val = sum(prices[-25:]) / 25
    signal = "bullish" if ma7 > ma25_val else "bearish" if ma7 < ma25_val else "neutral"
    return {"ma7": round(ma7, 4), "ma25": round(ma25_val, 4), "signal": signal}


# ---------------------------------------------------------------------------
# Per-signal scoring helpers (0.0 = bearish, 0.5 = neutral, 1.0 = bullish)
# ---------------------------------------------------------------------------

def _score_rsi(rsi_raw: Any) -> float:
    """Score RSI: <30 oversold=bullish, >70 overbought=bearish, 30-70 linear."""
    if isinstance(rsi_raw, dict):
        val = float(rsi_raw.get("value", 50))
    else:
        val = float(rsi_raw) if rsi_raw else 50.0
    if val < 30:
        return round(0.7 + (30 - val) / 30.0 * 0.3, 4)
    elif val > 70:
        return round(0.3 - (val - 70) / 30.0 * 0.3, 4)
    else:
        return round(0.3 + (val - 30) / 40.0 * 0.4, 4)


def _score_macd(macd_raw: Dict[str, Any]) -> float:
    """Score MACD: bullish cross=0.7-1.0, bearish cross=0.0-0.3, neutral=0.5."""
    if not isinstance(macd_raw, dict):
        return 0.5
    crossover = macd_raw.get("crossover", "neutral")
    hist = float(macd_raw.get("histogram", 0) or 0)
    if crossover == "bullish":
        return round(min(1.0, 0.7 + abs(hist) * 0.5), 4)
    elif crossover == "bearish":
        return round(max(0.0, 0.3 - abs(hist) * 0.5), 4)
    return 0.5


def _score_stochastic(stoch_raw: Dict[str, Any]) -> float:
    """Score Stochastic: K<20 & K>D = bullish, K>80 & K<D = bearish."""
    if not isinstance(stoch_raw, dict):
        return 0.5
    k = float(stoch_raw.get("k", 50))
    d = float(stoch_raw.get("d", 50))
    if k < 20 and k > d:
        return round(0.7 + (20 - k) / 20.0 * 0.3, 4)
    elif k > 80 and k < d:
        return round(0.3 - (k - 80) / 20.0 * 0.3, 4)
    return 0.5


def _score_bollinger(boll_raw: Dict[str, Any]) -> float:
    """Score Bollinger: price below lower band=bullish, above upper= bearish."""
    if not isinstance(boll_raw, dict):
        return 0.5
    sig = boll_raw.get("signal", "neutral")
    if sig == "oversold":
        return 0.85
    elif sig == "overbought":
        return 0.15
    return 0.5


def _score_mfi(mfi_raw: Dict[str, Any]) -> float:
    """Score MFI: <20 oversold=bullish, >80 overbought=bearish, 20-80 linear."""
    if not isinstance(mfi_raw, dict):
        return 0.5
    val = float(mfi_raw.get("mfi", 50))
    if val < 20:
        return round(0.7 + (20 - val) / 20.0 * 0.3, 4)
    elif val > 80:
        return round(0.3 - (val - 80) / 20.0 * 0.3, 4)
    else:
        return round(0.3 + (val - 20) / 60.0 * 0.4, 4)


def _score_cci(cci_raw: Dict[str, Any]) -> float:
    """Score CCI: <-100 oversold=bullish, >100 overbought=bearish, -100-100 linear."""
    if not isinstance(cci_raw, dict):
        return 0.5
    val = float(cci_raw.get("cci", 0))
    if val < -100:
        return round(0.7 + min(100, abs(val) - 100) / 100.0 * 0.3, 4)
    elif val > 100:
        return round(0.3 - min(100, val - 100) / 100.0 * 0.3, 4)
    else:
        return round(0.5 + val / 200.0, 4)


def _score_williams(williams_raw: Dict[str, Any]) -> float:
    """Score Williams %R: <-80 oversold=bullish, >-20 overbought=bearish."""
    if not isinstance(williams_raw, dict):
        return 0.5
    val = float(williams_raw.get("williams_r", -50))
    if val < -80:
        return round(0.7 + min(20, abs(val) - 80) / 20.0 * 0.3, 4)
    elif val > -20:
        return round(0.3 - (val + 20) / 80.0 * 0.3, 4)
    else:
        return round(0.5 + (val + 50) / 60.0 * 0.2, 4)


def _score_keltner(keltner_raw: Dict[str, Any]) -> float:
    """Score Keltner: price below lower band=bullish, above upper=bearish."""
    if not isinstance(keltner_raw, dict):
        return 0.5
    sig = keltner_raw.get("signal", "neutral")
    if sig == "oversold":
        return 0.85
    elif sig == "overbought":
        return 0.15
    return 0.5


# ---------------------------------------------------------------------------
# On-chain scoring helpers (TaoStats signals)
# ---------------------------------------------------------------------------

def _score_delegation_flow(sn: Dict[str, Any]) -> float:
    """Score net delegation flow over 24h.
    
    Positive net flow (incoming > outgoing) = bullish.
    Negative net flow = bearish.
    Falls back to 0.5 (neutral) when no flow data is available.
    """
    incoming = float(sn.get("delegation_incoming_24h", 0) or 0)
    outgoing = float(sn.get("delegation_outgoing_24h", 0) or 0)
    net = incoming - outgoing
    if net > 0:
        return round(min(1.0, 0.6 + net / (incoming + outgoing + 1) * 0.4), 4)
    elif net < 0:
        return round(max(0.0, 0.4 - abs(net) / (incoming + outgoing + 1) * 0.4), 4)
    return 0.5


def _score_staking_conviction(sn: Dict[str, Any]) -> float:
    """Score average staking conviction (lockup duration).
    
    Increasing average conviction = holders locking longer = bullish.
    Decreasing = holders exiting = bearish.
    Falls back to 0.5 when no conviction data is available.
    """
    current_conviction = float(sn.get("avg_conviction_current", 0) or 0)
    prev_conviction = float(sn.get("avg_conviction_prev", 0) or 0)
    if current_conviction > 0 and prev_conviction > 0:
        change = (current_conviction - prev_conviction) / prev_conviction
        if change > 0.01:
            return round(min(1.0, 0.6 + change * 0.4), 4)
        elif change < -0.01:
            return round(max(0.0, 0.4 - abs(change) * 0.4), 4)
    return 0.5


def _score_emission_momentum(sn: Dict[str, Any]) -> float:
    """Score current emission rate vs 7-day average.
    
    Accelerating emission = more capital flowing to subnet = bullish.
    Decelerating = bearish.
    Falls back to 0.5 when no emission data is available.
    """
    current = float(sn.get("emission", 0) or 0)
    ema_7d = float(sn.get("emission_ema_7d", 0) or 0)
    if current > 0 and ema_7d > 0:
        ratio = current / ema_7d
        if ratio > 1.02:
            return round(min(1.0, 0.6 + (ratio - 1.02) * 0.4), 4)
        elif ratio < 0.98:
            return round(max(0.0, 0.4 - (0.98 - ratio) * 0.4), 4)
    return 0.5


def _score_registration_cost(sn: Dict[str, Any]) -> float:
    """Score registration cost trend.
    
    Rising registration cost = increasing demand to mine = bullish.
    Falling registration cost = decreasing demand = bearish.
    Falls back to 0.5 when no registration cost data is available.
    """
    current_cost = float(sn.get("registration_cost_current", 0) or 0)
    prev_cost = float(sn.get("registration_cost_prev", 0) or 0)
    if current_cost > 0 and prev_cost > 0:
        change = (current_cost - prev_cost) / prev_cost
        if change > 0.01:
            return round(min(1.0, 0.6 + change * 0.4), 4)
        elif change < -0.01:
            return round(max(0.0, 0.4 - abs(change) * 0.4), 4)
    return 0.5


def _degraded_technical_indicators(hist: Dict[str, Any]) -> Dict[str, Any]:
    """Honest-empty technical payload when history is unavailable (SciWeave Q6)."""
    neutral = 0.5
    return {
        "rsi": {"value": 50.0, "signal": "neutral"},
        "stochastic": {"k": 50.0, "d": 50.0, "signal": "neutral"},
        "bollinger": {"upper": 0.0, "middle": 0.0, "lower": 0.0, "signal": "neutral"},
        "mfi": {"value": 50.0, "signal": "neutral"},
        "cci": {"value": 0.0, "signal": "neutral"},
        "williams_r": {"value": -50.0, "signal": "neutral"},
        "keltner": {"upper": 0.0, "middle": 0.0, "lower": 0.0, "signal": "neutral"},
        "macd": {"macd": 0.0, "signal": 0.0, "histogram": 0.0},
        "ma_cross": {"signal": "neutral"},
        "history_source": hist.get("source", "unavailable"),
        "history_length": len(hist.get("closes") or []),
        "degraded": True,
        "rsi_crossover": neutral,
        "macd_cross": neutral,
        "stochastic_reversal": neutral,
        "bollinger_squeeze": neutral,
        "mfi_flow": neutral,
        "cci_divergence": neutral,
        "williams_r": neutral,
        "keltner_channel": neutral,
    }


def _compute_technical_indicators(sn: Dict[str, Any]) -> Dict[str, Any]:
    """Compute all 8 indicators and return per-signal scores."""
    hist = _get_price_history(sn.get("netuid"), sn)
    closes = hist.get("closes", [])
    if hist.get("source") in ("synthetic", "unavailable") or len(closes) < 30:
        return _degraded_technical_indicators(hist)
    highs = hist.get("highs", closes)
    lows = hist.get("lows", closes)
    volumes = hist.get("volumes", [])

    rsi_raw = _compute_rsi_series(closes, 14)
    if len(closes) < 15:
        rsi_raw = 50.0

    macd_raw = _compute_macd_series(closes)
    stoch_raw = _compute_stochastic(highs, lows, closes)
    boll_raw = _compute_bollinger(closes)
    mfi_raw = _compute_mfi(highs, lows, closes, volumes)
    cci_raw = _compute_cci(highs, lows, closes)
    williams_raw = _compute_williams_r(highs, lows, closes)
    keltner_raw = _compute_keltner(closes, highs, lows)

    return {
        "rsi": {"value": rsi_raw, "signal": "overbought" if rsi_raw > 70 else "oversold" if rsi_raw < 30 else "neutral"},
        "stochastic": stoch_raw,
        "bollinger": boll_raw,
        "mfi": mfi_raw,
        "cci": cci_raw,
        "williams_r": williams_raw,
        "keltner": keltner_raw,
        "macd": macd_raw,
        "ma_cross": _compute_ma_cross(closes),
        "history_source": hist.get("source"),
        "history_length": len(closes),
        # Per-signal scores for weighted scoring
        "rsi_crossover": _score_rsi(rsi_raw),
        "macd_cross": _score_macd(macd_raw),
        "stochastic_reversal": _score_stochastic(stoch_raw),
        "bollinger_squeeze": _score_bollinger(boll_raw),
        "mfi_flow": _score_mfi(mfi_raw),
        "cci_divergence": _score_cci(cci_raw),
        "williams_r": _score_williams(williams_raw),
        "keltner_channel": _score_keltner(keltner_raw),
    }


def _compute_technical_score(
    sn: Dict[str, Any],
    horizon_type: str = "day",
) -> Dict[str, Any]:
    """Compute weighted technical score for a specific horizon type.

    Uses per-signal, per-horizon weights from soul_map.json to produce a
    single technical score (0.0-1.0), signal contributions, and the set of
    active signals that deviated meaningfully from neutral.
    """
    from internal.council.weights import load_signal_weights

    indicators = _compute_technical_indicators(sn)
    if indicators.get("degraded"):
        return {
            "technical_score": 0.5,
            "signal_contributions": {},
            "active_signals": [],
            "horizon_type": horizon_type,
            "degraded": True,
            "history_source": indicators.get("history_source", "unavailable"),
            "history_length": indicators.get("history_length", 0),
        }

    signal_weights = load_signal_weights()
    horizon_weights = signal_weights.get(horizon_type, signal_weights.get("day", {}))

    signal_names = [
        "rsi_crossover", "macd_cross", "stochastic_reversal",
        "bollinger_squeeze", "mfi_flow", "cci_divergence",
        "williams_r", "keltner_channel",
    ]

    weighted_sum = 0.0
    total_weight = 0.0
    contributions: Dict[str, Any] = {}

    for signal_name in signal_names:
        score = float(indicators.get(signal_name, 0.5))
        weight = float(horizon_weights.get(signal_name, 1.0))
        contributions[signal_name] = {
            "score": round(score, 4),
            "weight": round(weight, 4),
            "contribution": round(score * weight, 4),
        }
        weighted_sum += score * weight
        total_weight += weight

    tech_score = weighted_sum / total_weight if total_weight > 0 else 0.5

    return {
        "technical_score": round(tech_score, 4),
        "signal_contributions": contributions,
        "active_signals": [
            k for k, v in contributions.items()
            if v.get("score", 0.5) > 0.55 or v.get("score", 0.5) < 0.45
        ],
        "horizon_type": horizon_type,
    }


# ---------------------------------------------------------------------------
# Convergence detection
# ---------------------------------------------------------------------------
def _detect_oversold_convergence(indicators: Dict[str, Any]) -> Dict[str, Any]:
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

    rsi = indicators.get("rsi", {})
    rsi_val = float(rsi.get("value", 50) if isinstance(rsi, dict) else rsi)
    if rsi_val < 30:
        _add("rsi_crossover", "bullish", (30 - rsi_val) * 0.12, 24, 75, f"RSI {rsi_val:.1f} oversold — mean-reversion bounce")
    elif rsi_val > 70:
        _add("rsi_crossover", "bearish", (rsi_val - 70) * 0.12, 24, 75, f"RSI {rsi_val:.1f} overbought — pullback risk")
    else:
        _add("rsi_crossover", "neutral", 0.8, 24, 50, f"RSI {rsi_val:.1f} neutral — no edge")

    macd = indicators.get("macd", {})
    if isinstance(macd, dict):
        hist = float(macd.get("histogram", 0))
        crossover = macd.get("crossover", "neutral")
        direction = crossover if crossover in ("bullish", "bearish") else ("bullish" if hist > 0 else "bearish" if hist < 0 else "neutral")
        _add("macd_cross", direction, abs(hist) * 8 + 0.5, 48, 70, f"MACD histogram {hist:+.2f} ({crossover})")
    else:
        _add("macd_cross", "neutral", 0.5, 48, 50, "MACD unavailable")

    stoch = indicators.get("stochastic", {})
    if isinstance(stoch, dict):
        k = float(stoch.get("k", 50))
        signal = stoch.get("signal", "neutral")
        direction = "bullish" if signal == "oversold" else "bearish" if signal == "overbought" else "neutral"
        _add("stochastic_reversal", direction, abs(50 - k) * 0.08, 8, 65, f"Stochastic %K {k:.1f} ({signal})")
    else:
        _add("stochastic_reversal", "neutral", 0.5, 8, 50, "Stochastic unavailable")

    boll = indicators.get("bollinger", {})
    if isinstance(boll, dict):
        boll_signal = boll.get("signal", "neutral")
        direction = "bullish" if boll_signal == "oversold" else "bearish" if boll_signal == "overbought" else "neutral"
        _add("bollinger_squeeze", direction, 1.2 if direction != "neutral" else 0.4, 24, 60, f"Bollinger {boll_signal} (width {boll.get('bandwidth', 0):.2f})")
    else:
        _add("bollinger_squeeze", "neutral", 0.4, 24, 50, "Bollinger unavailable")

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

    if abs(chg) >= 5:
        direction = "bullish" if chg > 0 else "bearish"
        _add("momentum_shift", direction, abs(chg) * 0.5, 12, 72, f"24h change {chg:+.1f}% momentum")
    else:
        _add("momentum_shift", "neutral", 0.5, 12, 50, f"24h change {chg:+.1f}% muted")

    if emission > 1 and apy > 20:
        _add("emission_change", "bullish", emission * 0.3 + apy * 0.02, 168, 68, f"Emission {emission:.2f} TAO/day + {apy:.1f}% APY")
    elif emission < 0.05 or apy < 0:
        _add("emission_change", "bearish", 1.0, 168, 55, f"Weak emission {emission:.2f} / APY {apy:.1f}%")
    else:
        _add("emission_change", "neutral", 0.5, 168, 50, f"Emission {emission:.2f} TAO/day / APY {apy:.1f}%")

    mentions = int(sn.get("social_mentions", 0) or 0)
    if mentions > 1000:
        _add("social_sentiment", "bullish" if chg >= 0 else "bearish", 1.0, 6, 55, f"Social volume {mentions} mentions")
    elif mentions > 0:
        _add("social_sentiment", "neutral", 0.4, 6, 50, f"Social volume {mentions} mentions")

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
# Prediction helper (pure, no persistence)
# ---------------------------------------------------------------------------
def _expert_from_signal_source(source: Optional[str]) -> str:
    """Map signal labels to canonical Council experts (not legacy alpha/beta/gamma)."""
    if not source:
        return "quant"
    s = str(source).lower()
    if any(k in s for k in ("contrarian", "dark", "horse", "onchain", "on-chain", "flow")):
        return "dark_horse"
    if any(k in s for k in ("whale", "momentum", "hype", "social", "hot")):
        return "hype"
    if any(k in s for k in ("rsi", "stochastic", "williams", "cci", "macd", "technical", "indicator")):
        return "technical"
    if any(k in s for k in ("emission", "apy", "yield", "fundamental", "quant")):
        return "quant"
    return "quant"





def clamp_prediction_horizon(horizon: int, predicted_pct: Optional[float] = None) -> int:
    """Clamp a prediction horizon to a HARD 4-hour maximum.

    All predictions surfaced to users (API responses, homepage rendering, pick
    generation, signal-impact framing) must resolve within at most 4 hours.
    The previous magnitude-based banding (up to 168h) is intentionally removed
    so no prediction can ever advertise a horizon greater than 4 hours.

    Returns a horizon in ``[1, 4]``.
    """
    return max(1, min(int(horizon), 4))


def build_prediction_statement(
    sn: Dict[str, Any],
    predicted_pct: float,
    horizon: int,
    ref_price: float,
    signal_source: str,
    expert: str,
    now: _dt,
    signal_contributions: Optional[Dict[str, Any]] = None,
    horizon_type: str = "hour",
) -> Dict[str, Any]:
    """Build a predictive forecast dict without persisting it."""
    horizon = clamp_prediction_horizon(horizon, predicted_pct)
    prediction: Dict[str, Any] = {
        "id": _uuid.uuid4().hex[:10],
        "netuid": sn.get("netuid"),
        "name": sn.get("name"),
        "direction": "up" if predicted_pct >= 0 else "down",
        "predicted_pct": round(predicted_pct, 2),
        "horizon_hours": horizon,
        "reference_price": ref_price,
        "created_at": now.isoformat() + "Z",
        "resolve_at": (now + _td(hours=horizon)).isoformat() + "Z",
        "status": "pending",
        "signal_source": signal_source,
        "expert": expert,
        "statement": f"predicted to move {'+' if predicted_pct >= 0 else ''}{predicted_pct:.1f}% within {horizon} hours",
        "horizon_type": horizon_type,
    }
    if signal_contributions:
        prediction["signal_contributions"] = signal_contributions
    return prediction


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

    momentum_word = "accelerating" if chg7 > chg else "cooling" if chg7 < chg else "flat"
    if rsi_state == "overbought":
        rsi_note = f"RSI {rsi_val:.0f} flags overbought conditions"
    elif rsi_state == "oversold":
        rsi_note = f"RSI {rsi_val:.0f} sits in oversold territory"
    else:
        rsi_note = f"RSI {rsi_val:.0f} holds in neutral range"

    yield_note = f"{apy:.1f}% APY rewards stakers" if apy > 0 else "yield compression noted"
    emit_note = f"emission {emission:.0f} TAO/day" if emission > 0 else "no fresh emission"

    tw_text = f"${name} {momentum_word} — {chg:+.1f}% 24h / {chg7:+.1f}% 7d; {rsi_note}"
    discord_text = f"Validators weigh {emit_note} vs {yield_note}; 30d trend {chg30:+.1f}%"
    reddit_text = f"Volume {'surging' if volume > 0 else 'thin'} on SN{netuid} as momentum traders eye the {chg7:+.1f}% weekly move"

    feed = [
        {"source": "twitter", "sentiment": bias, "text": tw_text, "mentions": mentions},
        {"source": "discord", "sentiment": bias, "text": discord_text, "mentions": max(0, mentions // 2)},
        {"source": "reddit", "sentiment": bias if bias != "neutral" else "neutral", "text": reddit_text, "mentions": max(0, mentions // 3)},
    ]
    return {"score": score, "label": bias, "mentions": mentions, "feed": feed}


# ---------------------------------------------------------------------------
# Registry helper
# ---------------------------------------------------------------------------
def _load_registry() -> Dict[str, Any]:
    try:
        with open(_REGISTRY_PATH, "r") as f:
            return _json.load(f)
    except Exception:
        return {}


def _registry_info_for(netuid: Any, registry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not registry:
        return {}
    return registry.get(str(netuid)) or registry.get(int(netuid) if str(netuid).isdigit() else netuid) or {}


# ---------------------------------------------------------------------------
# State vector builder
# ---------------------------------------------------------------------------
def build_subnet_state_vector(netuid: int, subnets: List[dict], registry: Optional[dict] = None) -> Optional[dict]:
    """Build a reusable, serializable state vector for a single subnet."""
    sn = None
    for s in subnets:
        if s.get("netuid") == netuid:
            sn = s
            break
    if sn is None:
        return None

    if registry is None:
        registry = _load_registry()
    reg = _registry_info_for(netuid, registry)

    indicators = _compute_technical_indicators(sn)
    oversold = _detect_oversold_convergence(indicators)
    overbought = _detect_overbought_convergence(indicators)
    convergence = oversold if oversold.get("count", 0) >= overbought.get("count", 0) else overbought

    hot = _compute_hot_signals(sn, indicators, convergence)
    sell = _compute_sell_signals(sn, indicators, convergence)
    if sell.get("active"):
        hot = {**hot, "active": False, "label": None, "suppressed_by": "SELL ALERT"}

    signal_impact = _compute_signal_impact(sn, indicators, hot, sell)
    prediction = build_prediction_statement(
        sn=sn,
        predicted_pct=signal_impact.get("net_predicted_pct", 0) or 1.5,
        horizon=24,
        ref_price=float(sn.get("price", 0) or 0) or 1.0,
        signal_source=signal_impact.get("dominant") or signal_impact.get("net_direction", "neutral"),
        expert=_expert_from_signal_source(signal_impact.get("dominant") or signal_impact.get("net_direction", "neutral")),
        now=_dt.utcnow(),
    )
    social_sentiment = _compute_social_sentiment(sn)

    consensus_score = round((hot.get("score", 0) - sell.get("score", 0) + 5) / 10, 2)
    consensus_action = "accumulate" if consensus_score >= 0.75 else "reduce" if consensus_score <= 0.4 else "hold"

    return {
        "netuid": netuid,
        "name": sn.get("name"),
        "status": sn.get("status", "unknown"),
        "sector": sn.get("sector", reg.get("sector", "Unknown")),
        "metrics": {
            "emission": float(sn.get("emission", 0) or 0),
            "apy": float(sn.get("apy", 0) or 0),
            "price": float(sn.get("price", 0) or 0),
            "price_change_24h": float(sn.get("price_change_24h", 0) or 0),
            "price_change_7d": float(sn.get("price_change_7d", 0) or 0),
            "price_change_30d": float(sn.get("price_change_30d", 0) or 0),
            "volume": float(sn.get("volume", 0) or 0),
            "market_cap": float(sn.get("market_cap", 0) or 0),
            "total_stake": float(sn.get("total_stake", 0) or reg.get("total_stake", 0) or 0),
            "social_mentions": int(sn.get("social_mentions", 0) or 0),
            "is_overvalued": bool(sn.get("is_overvalued", False)),
            "risk_flags": sn.get("risk_flags", []),
        },
        "technical_indicators": indicators,
        "convergence": convergence,
        "hot": hot,
        "sell": sell,
        "signal_impact": signal_impact,
        "prediction": prediction,
        "social_sentiment": social_sentiment,
        "consensus": {"action": consensus_action, "score": consensus_score},
        "timestamp": _dt.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Council expert scoring
# ---------------------------------------------------------------------------
def _compute_onchain_quant_score(sn: Dict[str, Any]) -> float:
    """Compute quant expert score from on-chain fundamentals.

    Combines emission_momentum, staking_conviction, and registration_cost
    into a single quant score. These are fundamental economics — not price-based.
    """
    weights = {"emission_momentum": 0.4, "staking_conviction": 0.3, "registration_cost": 0.3}
    score = 0.0
    total_w = 0.0

    emission = _score_emission_momentum(sn)
    conviction = _score_staking_conviction(sn)
    reg_cost = _score_registration_cost(sn)

    for name, val in [("emission_momentum", emission), ("staking_conviction", conviction), ("registration_cost", reg_cost)]:
        w = weights.get(name, 1.0)
        score += val * w
        total_w += w

    return round(score / total_w, 4) if total_w > 0 else 0.5


def _compute_hype_score(sn: Dict[str, Any]) -> float:
    """Compute hype expert score from delegation flow.

    Delegation flow (capital moving in/out of a subnet) is a pure sentiment/momentum
    signal — delegators voting with their TAO. Belongs to Hype, not Quant.
    """
    return _score_delegation_flow(sn)


def _compute_dark_horse_score(sn: Dict[str, Any]) -> float:
    """Compute Dark Horse expert score from on-chain flow signals.

    The Dark Horse uses signals that are uncorrelated with price charts:
    - TAO pool depth: rising TAO in subnet pool = conviction
    - Supply contraction: circulating supply dropping relative to market cap = accumulation
    - Price/emission ratio: how much price per unit emission (undervaluation)

    Falls back to 0.5 (neutral) when data is unavailable.
    """
    # TAO pool depth — ratio of subnet TAO pool to total stake
    tao_pool = float(sn.get("tao_pool", 0) or 0)
    total_stake = float(sn.get("total_stake", 0) or 1)
    pool_ratio = tao_pool / total_stake if total_stake > 0 else 0
    # Higher ratio = more conviction = bullish
    pool_score = 0.5
    if pool_ratio > 0.1:
        pool_score = min(1.0, 0.5 + pool_ratio * 2.0)
    elif pool_ratio > 0.05:
        pool_score = 0.6
    elif pool_ratio > 0.01:
        pool_score = 0.55

    # Supply contraction — circulating supply change
    circ_supply = float(sn.get("circulating_supply", 0) or 0)
    prev_supply = float(sn.get("circulating_supply_prev", 0) or 0)
    supply_score = 0.5
    if circ_supply > 0 and prev_supply > 0:
        supply_change = (circ_supply - prev_supply) / prev_supply
        if supply_change < -0.01:  # contracting supply = accumulation
            supply_score = min(1.0, 0.6 + abs(supply_change) * 5.0)
        elif supply_change > 0.01:  # expanding supply = dilution
            supply_score = max(0.0, 0.4 - supply_change * 5.0)

    # Price/emission ratio — undervaluation signal
    price = float(sn.get("price", 0) or 0)
    emission = float(sn.get("emission", 0) or 1)
    if price > 0 and emission > 0:
        pe_ratio = price / emission
        # Compare to market average — below average = undervalued
        # We'll normalize relative to a reasonable range
        if pe_ratio < 0.5:
            pe_score = 0.8  # significantly undervalued
        elif pe_ratio < 1.0:
            pe_score = 0.65
        elif pe_ratio < 2.0:
            pe_score = 0.5
        elif pe_ratio < 5.0:
            pe_score = 0.4
        else:
            pe_score = 0.3  # overvalued
    else:
        pe_score = 0.5

    # Weighted combination
    dark_horse_score = pool_score * 0.4 + supply_score * 0.3 + pe_score * 0.3
    return round(dark_horse_score, 4)


_DEFAULT_WEIGHTS = {
    "quant": 0.30,
    "hype": 0.25,
    "dark_horse": 0.20,
    "technical": 0.25,
}


def _expert_contributions(
    sn: Dict[str, Any],
    indicators: Dict[str, Any],
    signal_impact: Dict[str, Any],
    hot: Dict[str, Any],
    sell: Dict[str, Any],
) -> Dict[str, float]:
    """Return deterministic 0-1 scores for the four council experts."""
    emission = float(sn.get("emission", 0) or 0)
    apy = float(sn.get("apy", 0) or 0)
    volume = float(sn.get("volume", 0) or 0)
    market_cap = float(sn.get("market_cap", 0) or 0)
    mentions = int(sn.get("social_mentions", 0) or 0)
    chg24 = float(sn.get("price_change_24h", 0) or 0)
    chg7 = float(sn.get("price_change_7d", 0) or 0)

    rsi = indicators.get("rsi", {}) if isinstance(indicators.get("rsi"), dict) else {"value": 50}
    macd = indicators.get("macd", {}) if isinstance(indicators.get("macd"), dict) else {}
    ma = indicators.get("ma_cross", {}) if isinstance(indicators.get("ma_cross"), dict) else {}

    # Quant: emission stability + yield + liquidity
    quant = 0.45
    quant += min(0.25, emission * 0.08)
    quant += min(0.20, apy * 0.006)
    quant += 0.10 if volume > 500_000 else 0.0
    quant += 0.10 if market_cap > 10_000_000 else 0.0
    quant = min(1.0, max(0.0, quant))

    # Hype: social volume + short-term momentum
    hype = 0.45
    hype += min(0.30, mentions / 5_000.0)
    hype += min(0.15, chg24 / 20.0)
    hype += min(0.10, chg7 / 30.0)
    hype = min(1.0, max(0.0, hype))

    # Dark Horse: uncorrelated on-chain flow signals
    dark_horse = _compute_dark_horse_score(sn)

    # Technical: indicator consensus
    technical = 0.50
    if macd.get("crossover") == "bullish":
        technical += 0.15
    elif macd.get("crossover") == "bearish":
        technical -= 0.15
    if ma.get("signal") == "bullish":
        technical += 0.10
    elif ma.get("signal") == "bearish":
        technical -= 0.10
    if hot.get("active"):
        technical += 0.10
    if sell.get("active"):
        technical -= 0.20
    technical = min(1.0, max(0.0, technical))

    return {
        "quant": round(quant, 4),
        "hype": round(hype, 4),
        "dark_horse": round(dark_horse, 4),
        "technical": round(technical, 4),
    }


def _scenario_tags(
    sn: Dict[str, Any],
    indicators: Dict[str, Any],
    market_context: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    """Derive granular regime, RSI, volume and price-direction scenario tags.

    Volume buckets are tuned to per-subnet USD turnover rather than the old
    network-wide thresholds: ``very_low`` (<$500), ``low`` ($500-$5k),
    ``medium`` ($5k-$50k), ``high`` (>$50k). RSI bands are tightened so the
    neutral band is narrower (oversold <35, neutral 35-65, overbought >65),
    giving the learning loop more signal to separate from noise. When the
    regime is neutral it is further split by the sign of the 24h change
    (``neutral_bullish`` / ``neutral_bearish`` / ``neutral``) so flat-but-
    trending markets are still distinguishable. A ``price_direction`` field
    captures the raw up/down move for downstream scenario matching.
    """
    market_context = market_context or {}
    tao_chg = float(market_context.get("tao_change_24h", 0) or 0)
    if tao_chg > 3:
        regime = "bullish"
    elif tao_chg < -3:
        regime = "bearish"
    else:
        # Neutral regime: sub-classify by the sign of the 24h change so the
        # learning loop can still tell a flat-but-rising market from a
        # flat-but-falling one.
        if tao_chg > 0:
            regime = "neutral_bullish"
        elif tao_chg < 0:
            regime = "neutral_bearish"
        else:
            regime = "neutral"

    rsi_val = 50.0
    rsi = indicators.get("rsi", {})
    if isinstance(rsi, dict):
        rsi_val = float(rsi.get("value", 50))
    if rsi_val < 35:
        rsi_tag = "oversold"
    elif rsi_val > 65:
        rsi_tag = "overbought"
    else:
        rsi_tag = "neutral"

    volume = float(sn.get("volume", 0) or 0)
    if volume < 500:
        volume_tag = "very_low"
    elif volume < 5_000:
        volume_tag = "low"
    elif volume < 50_000:
        volume_tag = "medium"
    else:
        volume_tag = "high"

    price_change_24h = float(sn.get("price_change_24h", 0) or 0)
    price_direction = "up" if price_change_24h >= 0 else "down"

    from internal.subnets.apy import undervalued_verdict

    return {
        "regime": regime,
        "rsi": rsi_tag,
        "volume": volume_tag,
        "price_direction": price_direction,
        "valuation": undervalued_verdict(sn),
    }


def _resolver_hit_rate(min_n: int = 30) -> Optional[float]:
    """Return historical resolver accuracy when enough graded outcomes exist."""
    try:
        from internal.council.resolver import PREDICTIONS_PATH

        with open(PREDICTIONS_PATH, "r") as f:
            data = _json.load(f)
    except Exception:
        return None

    resolved = data.get("resolved", [])
    graded = [
        p for p in resolved
        if isinstance(p, dict) and p.get("correct") is not None
    ]
    if len(graded) < min_n:
        return None

    hits = sum(1 for p in graded if p.get("correct") is True)
    return hits / len(graded)


def _compute_confidence(
    sn: Dict[str, Any],
    indicators: Dict[str, Any],
    expert_contributions: Dict[str, float],
) -> float:
    """Return a 0-1 confidence score calibrated against resolver history."""
    prior = _resolver_hit_rate()
    if prior is None:
        prior = 0.5

    required = ("netuid", "name", "price", "volume")
    missing = sum(1 for f in required if sn.get(f) is None or sn.get(f) == "")
    completeness = 1.0 - missing * 0.15

    hist_len = int(indicators.get("history_length", 0) or 0)
    if hist_len < 15:
        completeness -= 0.15
    elif hist_len < 30:
        completeness -= 0.05

    if float(sn.get("volume", 0) or 0) <= 0:
        completeness -= 0.10

    completeness = min(1.0, max(0.0, completeness))

    scores = [
        float(v) for v in expert_contributions.values()
        if isinstance(v, (int, float))
    ]
    if scores:
        dispersion = max(scores) - min(scores)
        agreement = max(0.0, 1.0 - dispersion)
    else:
        agreement = 0.5

    confidence = prior * completeness * (0.75 + 0.25 * agreement)
    return round(min(1.0, max(0.0, confidence)), 4)


def score_subnet_for_hour(
    subnet_data: Dict[str, Any],
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Short-horizon score (0-100) emphasizing momentum and immediate signals."""
    sn = subnet_data or {}
    indicators = _compute_technical_indicators(sn)
    convergence = _detect_oversold_convergence(indicators)
    hot = _compute_hot_signals(sn, indicators, convergence)
    sell = _compute_sell_signals(sn, indicators, convergence)
    signal_impact = _compute_signal_impact(sn, indicators, hot, sell)

    experts = _expert_contributions(sn, indicators, signal_impact, hot, sell)
    try:
        from internal.signal_hub.overlay import apply_hub_overlay

        netuid = sn.get("netuid") or sn.get("id")
        hub_map = (market_context or {}).get("hub_overlay") or {}
        overlay = hub_map.get(int(netuid)) if netuid is not None else None
        experts = apply_hub_overlay(experts, overlay)
    except Exception:
        pass
    weights = dict(_DEFAULT_WEIGHTS)
    if market_context and isinstance(market_context.get("weights"), dict):
        weights.update(market_context["weights"])

    # Hour lens: overweight hype/technical, underweight dark_horse
    hour_weights = {
        "quant": weights.get("quant", 0.30) * 0.90,
        "hype": weights.get("hype", 0.25) * 1.20,
        "dark_horse": weights.get("dark_horse", 0.20) * 0.80,
        "technical": weights.get("technical", 0.25) * 1.10,
    }
    total_weight = sum(hour_weights.values()) or 1.0
    hour_weights = {k: v / total_weight for k, v in hour_weights.items()}

    weighted = sum(experts[k] * hour_weights[k] for k in experts)
    chg24 = float(sn.get("price_change_24h", 0) or 0)
    momentum_boost = max(-0.10, min(0.10, chg24 / 100.0))
    total = round((weighted + momentum_boost) * 100, 2)
    total = min(100.0, max(0.0, total))

    confidence = _compute_confidence(sn, indicators, experts)
    tags = _scenario_tags(sn, indicators, market_context)

    # Compute weighted technical score for hour horizon
    tech_score = _compute_technical_score(sn, "hour")

    return {
        "total_score": total,
        "expert_contributions": {
            **experts,
            "signal_contributions": tech_score["signal_contributions"],
            "active_signals": tech_score["active_signals"],
            "technical_score": tech_score["technical_score"],
        },
        "confidence": confidence,
        "scenario_tags": tags,
        "horizon": "hour",
        "horizon_type": "hour",
        "weights_used": hour_weights,
    }


def score_subnet_for_day(
    subnet_data: Dict[str, Any],
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """24h score (0-100) emphasizing yield, trend, and lower volatility."""
    sn = subnet_data or {}
    indicators = _compute_technical_indicators(sn)
    convergence = _detect_oversold_convergence(indicators)
    hot = _compute_hot_signals(sn, indicators, convergence)
    sell = _compute_sell_signals(sn, indicators, convergence)
    signal_impact = _compute_signal_impact(sn, indicators, hot, sell)

    experts = _expert_contributions(sn, indicators, signal_impact, hot, sell)
    try:
        from internal.signal_hub.overlay import apply_hub_overlay

        netuid = sn.get("netuid") or sn.get("id")
        hub_map = (market_context or {}).get("hub_overlay") or {}
        overlay = hub_map.get(int(netuid)) if netuid is not None else None
        experts = apply_hub_overlay(experts, overlay)
    except Exception:
        pass
    weights = dict(_DEFAULT_WEIGHTS)
    if market_context and isinstance(market_context.get("weights"), dict):
        weights.update(market_context["weights"])

    # Day lens: overweight quant/dark_horse, underweight hype
    day_weights = {
        "quant": weights.get("quant", 0.30) * 1.15,
        "hype": weights.get("hype", 0.25) * 0.80,
        "dark_horse": weights.get("dark_horse", 0.20) * 1.10,
        "technical": weights.get("technical", 0.25) * 0.95,
    }
    total_weight = sum(day_weights.values()) or 1.0
    day_weights = {k: v / total_weight for k, v in day_weights.items()}

    weighted = sum(experts[k] * day_weights[k] for k in experts)
    from internal.subnets.apy import undervalued_score

    value_gap = undervalued_score(sn)
    if value_gap is None:
        value_gap = 0.0
    # Reward yield ahead of 24h price (lagging price = undervalued), not 7d/30d momentum.
    value_boost = max(-0.10, min(0.10, value_gap / 100.0))
    total = round((weighted + value_boost) * 100, 2)
    total = min(100.0, max(0.0, total))

    confidence = _compute_confidence(sn, indicators, experts)
    tags = _scenario_tags(sn, indicators, market_context)

    # Compute weighted technical score for day horizon
    tech_score = _compute_technical_score(sn, "day")

    return {
        "total_score": total,
        "expert_contributions": {
            **experts,
            "signal_contributions": tech_score["signal_contributions"],
            "active_signals": tech_score["active_signals"],
            "technical_score": tech_score["technical_score"],
        },
        "confidence": confidence,
        "scenario_tags": tags,
        "horizon": "day",
        "horizon_type": "day",
        "weights_used": day_weights,
    }


# ---------------------------------------------------------------------------
# Top-pick formatter
# ---------------------------------------------------------------------------
def format_top_pick(state_vector: Dict[str, Any], rank: int) -> Dict[str, Any]:
    """Convert a state vector into the public top-pick shape."""
    metrics = state_vector.get("metrics", {})
    return {
        "rank": rank,
        "netuid": state_vector.get("netuid"),
        "name": state_vector.get("name"),
        "score": state_vector.get("_score", 0.0),
        "emission": metrics.get("emission"),
        "apy": metrics.get("apy"),
        "price_change_24h": metrics.get("price_change_24h"),
        "signal_impact": state_vector.get("signal_impact"),
        "hot": state_vector.get("hot"),
        "sell": state_vector.get("sell"),
        "technical_indicators": state_vector.get("technical_indicators"),
        "timestamp": state_vector.get("timestamp"),
    }


def _compute_simivision_reasons(sn: Dict[str, Any], indicators: Dict[str, Any], hot: Dict[str, Any]) -> List[str]:
    """Generate a short list of reasons for a SimiVision pick."""
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
