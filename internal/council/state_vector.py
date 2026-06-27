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


def _get_price_history(netuid: Any, sn: Dict[str, Any]) -> Dict[str, Any]:
    """Return {closes, highs, lows, volumes, timestamps, source} for a subnet."""
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
                steps.append(chg_30d / 10.0)
            elif i < 22:
                steps.append(chg_7d / 12.0)
            else:
                steps.append(chg_24h / 8.0)
        steps = [s if abs(s) < 50 else (50 if s > 0 else -50) for s in steps]
        p = price
        synth_closes = []
        for i, s in enumerate(steps):
            amp = max(2.0, abs(s) * 2.0)
            osc = _math.sin(i * 0.7) * amp
            p = p * (1 + s / 100.0) * (1 + osc / 100.0)
            synth_closes.append(p)
        closes = (closes + synth_closes)[-30:]
        highs = [c * 1.01 for c in closes]
        lows = [c * 0.99 for c in closes]
        base_vol = float(sn.get("volume", 0) or 0) / max(len(closes), 1)
        volumes = [base_vol for _ in closes]
        timestamps = timestamps[-len(closes):] or ["" for _ in closes]
        source = "synthetic" if not timestamps or not timestamps[0] else source

    return {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes, "timestamps": timestamps, "source": source}


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

    return {
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


def build_prediction_statement(
    sn: Dict[str, Any],
    predicted_pct: float,
    horizon: int,
    ref_price: float,
    signal_source: str,
    expert: str,
    now: _dt,
) -> Dict[str, Any]:
    """Build a predictive forecast dict without persisting it."""
    return {
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
_DEFAULT_WEIGHTS = {
    "quant": 0.30,
    "hype": 0.25,
    "contrarian": 0.20,
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
    is_overvalued = bool(sn.get("is_overvalued", False))

    rsi = indicators.get("rsi", {}) if isinstance(indicators.get("rsi"), dict) else {"value": 50}
    rsi_val = float(rsi.get("value", 50))
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

    # Contrarian: inverse overvaluation, mean-reversion to RSI extremes
    contrarian = 0.50
    if is_overvalued:
        contrarian -= 0.30
    if rsi_val < 30:
        contrarian += 0.35
    elif rsi_val > 70:
        contrarian -= 0.25
    contrarian = min(1.0, max(0.0, contrarian))

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
        "contrarian": round(contrarian, 4),
        "technical": round(technical, 4),
    }


def _scenario_tags(
    sn: Dict[str, Any],
    indicators: Dict[str, Any],
    market_context: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    """Derive regime, RSI and volume scenario tags."""
    market_context = market_context or {}
    tao_chg = float(market_context.get("tao_change_24h", 0) or 0)
    if tao_chg > 3:
        regime = "bullish"
    elif tao_chg < -3:
        regime = "bearish"
    else:
        regime = "neutral"

    rsi_val = 50.0
    rsi = indicators.get("rsi", {})
    if isinstance(rsi, dict):
        rsi_val = float(rsi.get("value", 50))
    if rsi_val < 30:
        rsi_tag = "oversold"
    elif rsi_val > 70:
        rsi_tag = "overbought"
    else:
        rsi_tag = "neutral"

    volume = float(sn.get("volume", 0) or 0)
    if volume > 1_000_000:
        volume_tag = "high"
    elif volume < 100_000:
        volume_tag = "low"
    else:
        volume_tag = "normal"

    return {"regime": regime, "rsi": rsi_tag, "volume": volume_tag}


def _compute_confidence(
    sn: Dict[str, Any],
    indicators: Dict[str, Any],
    expert_contributions: Dict[str, float],
) -> float:
    """Return a 0-1 confidence score based on data completeness and consensus."""
    confidence = 0.55

    required = ("netuid", "name", "price", "volume")
    missing = sum(1 for f in required if sn.get(f) is None or sn.get(f) == "")
    confidence -= missing * 0.10

    if float(sn.get("volume", 0) or 0) > 0:
        confidence += 0.10
    if float(sn.get("price_change_24h", 0) is not None):
        confidence += 0.05
    if float(sn.get("price_change_7d", 0) is not None):
        confidence += 0.05

    hist_len = int(indicators.get("history_length", 0) or 0)
    if hist_len >= 30:
        confidence += 0.10
    elif hist_len >= 15:
        confidence += 0.05

    scores = list(expert_contributions.values())
    if scores:
        dispersion = max(scores) - min(scores)
        confidence -= dispersion * 0.10

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
    weights = dict(_DEFAULT_WEIGHTS)
    if market_context and isinstance(market_context.get("weights"), dict):
        weights.update(market_context["weights"])

    # Hour lens: overweight hype/technical, underweight contrarian
    hour_weights = {
        "quant": weights.get("quant", 0.30) * 0.90,
        "hype": weights.get("hype", 0.25) * 1.20,
        "contrarian": weights.get("contrarian", 0.20) * 0.80,
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

    return {
        "total_score": total,
        "expert_contributions": experts,
        "confidence": confidence,
        "scenario_tags": tags,
        "horizon": "hour",
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
    weights = dict(_DEFAULT_WEIGHTS)
    if market_context and isinstance(market_context.get("weights"), dict):
        weights.update(market_context["weights"])

    # Day lens: overweight quant/contrarian, underweight hype
    day_weights = {
        "quant": weights.get("quant", 0.30) * 1.15,
        "hype": weights.get("hype", 0.25) * 0.80,
        "contrarian": weights.get("contrarian", 0.20) * 1.10,
        "technical": weights.get("technical", 0.25) * 0.95,
    }
    total_weight = sum(day_weights.values()) or 1.0
    day_weights = {k: v / total_weight for k, v in day_weights.items()}

    weighted = sum(experts[k] * day_weights[k] for k in experts)
    chg7 = float(sn.get("price_change_7d", 0) or 0)
    chg30 = float(sn.get("price_change_30d", 0) or 0)
    trend_boost = max(-0.10, min(0.10, (chg7 * 0.6 + chg30 * 0.4) / 100.0))
    total = round((weighted + trend_boost) * 100, 2)
    total = min(100.0, max(0.0, total))

    confidence = _compute_confidence(sn, indicators, experts)
    tags = _scenario_tags(sn, indicators, market_context)

    return {
        "total_score": total,
        "expert_contributions": experts,
        "confidence": confidence,
        "scenario_tags": tags,
        "horizon": "day",
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
