"""Recovery-vs-correction evidence for scored subnet rows.

This module deliberately reports unavailable evidence as ``unknown`` rather
than treating missing market data as a recovery or a correction.  The council
can use this context for future score policy, while the current score remains
backward-compatible.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _number(row: Dict[str, Any], key: str) -> Optional[float]:
    value = row.get(key)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _history_series(history: Optional[Dict[str, Any]], key: str) -> List[float]:
    values = (history or {}).get(key) or []
    out: List[float] = []
    for value in values:
        try:
            out.append(float(value))
        except (TypeError, ValueError):
            continue
    return out


def _trend_context(sn: Dict[str, Any]) -> Dict[str, Any]:
    change_7d = _number(sn, "price_change_7d")
    change_30d = _number(sn, "price_change_30d")
    available = change_7d is not None or change_30d is not None

    if change_7d is not None and change_30d is not None:
        if change_7d <= -5.0 and change_30d <= -8.0:
            label = "prolonged_downtrend"
        elif change_7d <= -5.0 and change_30d > -5.0:
            label = "recent_pullback"
        elif change_7d >= 5.0 and change_30d >= 5.0:
            label = "sustained_uptrend"
        else:
            label = "mixed"
    elif change_7d is not None:
        label = "weekly_downtrend" if change_7d <= -5.0 else (
            "weekly_uptrend" if change_7d >= 5.0 else "weekly_flat"
        )
    elif change_30d is not None:
        label = "monthly_downtrend" if change_30d <= -8.0 else (
            "monthly_uptrend" if change_30d >= 8.0 else "monthly_flat"
        )
    else:
        label = "unknown"

    return {
        "status": label if available else "unknown",
        "available": available,
        "price_change_7d": change_7d,
        "price_change_30d": change_30d,
    }


def _recent_move_context(sn: Dict[str, Any]) -> Dict[str, Any]:
    change_24h = _number(sn, "price_change_24h")
    change_7d = _number(sn, "price_change_7d")
    change_30d = _number(sn, "price_change_30d")
    daily_7d = change_7d / 7.0 if change_7d is not None else None
    daily_30d = change_30d / 30.0 if change_30d is not None else None
    comparison = None
    if change_24h is not None and daily_7d is not None:
        comparison = round(change_24h - daily_7d, 4)

    if change_24h is None:
        status = "unknown"
    elif change_7d is not None and change_7d <= -5.0:
        # This mirrors the existing recovery heuristic, but only marks
        # recovery when the broader decline is actually available.
        status = "improving" if change_24h > change_7d * 0.3 else "continuing_decline"
    elif change_7d is not None:
        status = "positive_recent_move" if change_24h > 0 else "negative_recent_move"
    else:
        status = "recent_move_only"

    return {
        "status": status,
        "available": change_24h is not None,
        "price_change_24h": change_24h,
        "daily_average_7d": round(daily_7d, 4) if daily_7d is not None else None,
        "daily_average_30d": round(daily_30d, 4) if daily_30d is not None else None,
        "recent_vs_7d_daily_average": comparison,
    }


def _price_structure_context(history: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    lows = _history_series(history, "lows")
    closes = _history_series(history, "closes")
    source = (history or {}).get("source", "unavailable")
    available = len(lows) >= 3 and len(closes) >= 2
    if not available:
        return {
            "status": "unknown",
            "available": False,
            "higher_lows": None,
            "lower_lows": None,
            "positive_reversal": None,
            "history_source": source,
            "history_length": max(len(lows), len(closes)),
        }

    higher_lows = lows[-1] > lows[-2] and lows[-2] >= lows[-3]
    lower_lows = lows[-1] < lows[-2] and lows[-2] <= lows[-3]
    positive_reversal = closes[-1] > closes[-2]
    if higher_lows and positive_reversal:
        status = "recovery_structure"
    elif lower_lows:
        status = "lower_low"
    elif positive_reversal:
        status = "positive_close_only"
    else:
        status = "no_reversal"

    return {
        "status": status,
        "available": True,
        "higher_lows": higher_lows,
        "lower_lows": lower_lows,
        "positive_reversal": positive_reversal,
        "history_source": source,
        "history_length": max(len(lows), len(closes)),
    }


def _technical_reversal_context(indicators: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    indicators = indicators or {}
    if indicators.get("degraded"):
        return {
            "status": "unknown",
            "available": False,
            "rsi": None,
            "rsi_signal": None,
            "macd_crossover": None,
            "macd_histogram": None,
        }

    rsi = indicators.get("rsi") if isinstance(indicators.get("rsi"), dict) else {}
    macd = indicators.get("macd") if isinstance(indicators.get("macd"), dict) else {}
    rsi_value = _number(rsi, "value")
    rsi_signal = rsi.get("signal")
    macd_crossover = macd.get("crossover")
    macd_histogram = _number(macd, "histogram")
    available = rsi_value is not None or macd_crossover is not None

    # A bullish MACD turn with RSI not overbought is confirmation; a bearish
    # MACD state is contrary evidence, not a recovery confirmation.
    if macd_crossover == "bullish" and rsi_signal in ("oversold", "neutral"):
        status = "confirmed_reversal"
    elif macd_crossover == "bearish":
        status = "bearish_confirmation"
    elif available:
        status = "mixed_or_unconfirmed"
    else:
        status = "unknown"

    return {
        "status": status,
        "available": available,
        "rsi": rsi_value,
        "rsi_signal": rsi_signal,
        "macd_crossover": macd_crossover,
        "macd_histogram": macd_histogram,
    }


def _flow_context(
    sn: Dict[str, Any],
    history: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    incoming = _number(sn, "delegation_incoming_24h")
    outgoing = _number(sn, "delegation_outgoing_24h")
    buy_volume = _number(sn, "buy_volume_24h")
    sell_volume = _number(sn, "sell_volume_24h")
    volumes = _history_series(history, "volumes")
    volume_ratio = None
    if len(volumes) >= 2 and volumes[-1] > 0:
        baseline = sum(volumes[:-1]) / max(1, len(volumes) - 1)
        if baseline > 0:
            volume_ratio = round(volumes[-1] / baseline, 4)

    net_delegation = round(incoming - outgoing, 4) if incoming is not None and outgoing is not None else None
    net_trade_flow = round(buy_volume - sell_volume, 4) if buy_volume is not None and sell_volume is not None else None
    available = net_delegation is not None or net_trade_flow is not None or volume_ratio is not None
    positive = (net_delegation is not None and net_delegation > 0) or (
        net_trade_flow is not None and net_trade_flow > 0
    )
    negative = (net_delegation is not None and net_delegation < 0) or (
        net_trade_flow is not None and net_trade_flow < 0
    )
    if not available:
        status = "unknown"
    elif positive and volume_ratio is not None and volume_ratio >= 1.0:
        status = "confirmed_positive_flow"
    elif negative:
        status = "negative_flow"
    elif positive:
        status = "positive_flow"
    else:
        status = "neutral_flow"

    return {
        "status": status,
        "available": available,
        "volume_ratio": volume_ratio,
        "net_delegation_24h": net_delegation,
        "net_trade_flow_24h": net_trade_flow,
    }


# Haircut fractions applied to a long-horizon score when correction evidence
# outweighs recovery evidence.  Kept small and bounded so a haircut re-ranks
# risky names rather than zeroing them out.
HIGH_RISK_HAIRCUT = 0.15
ELEVATED_RISK_HAIRCUT = 0.08


def recovery_risk_adjustment(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Translate recovery-vs-correction evidence into an explicit score guard.

    Returns a dict with:
    - ``applied``: whether a haircut should be applied
    - ``haircut``: fraction (0-1) to shave off the long score
    - ``reason``: machine-readable explanation for audit/UI

    Mean-reversion candidates are preserved: when the classification is
    ``recovery_candidate`` (>=2 independent recovery evidence cells) no
    haircut is applied even in a downtrend.  Missing evidence stays neutral —
    unknown never triggers a haircut.
    """
    context = context or {}
    classification = context.get("classification")
    if classification == "recovery_candidate":
        return {
            "applied": False,
            "haircut": 0.0,
            "reason": "recovery_evidence_present",
            "classification": classification,
        }
    if classification != "correction_risk":
        return {
            "applied": False,
            "haircut": 0.0,
            "reason": "evidence_inconclusive",
            "classification": classification,
        }

    trend = (context.get("trend_context") or {}).get("status")
    technical = (context.get("technical_reversal") or {}).get("status")
    flow = (context.get("flow_confirmation") or {}).get("status")
    lower_lows = bool(
        (context.get("lower_lows_without_recovery") or {}).get("detected")
    )
    flow_positive = flow in ("confirmed_positive_flow", "positive_flow")

    high_risk = (
        lower_lows
        or (trend == "prolonged_downtrend" and technical == "bearish_confirmation")
    )
    if high_risk and not flow_positive:
        return {
            "applied": True,
            "haircut": HIGH_RISK_HAIRCUT,
            "reason": "prolonged_downtrend_no_recovery_confirmation",
            "classification": classification,
        }
    return {
        "applied": True,
        "haircut": ELEVATED_RISK_HAIRCUT,
        "reason": "correction_risk_elevated",
        "classification": classification,
    }


def build_recovery_context(
    sn: Dict[str, Any],
    indicators: Optional[Dict[str, Any]] = None,
    history: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return six honest evidence cells for recovery-vs-correction analysis."""
    trend = _trend_context(sn)
    recent = _recent_move_context(sn)
    structure = _price_structure_context(history)
    technical = _technical_reversal_context(indicators)
    flow = _flow_context(sn, history)

    downtrend = trend["status"] in {
        "prolonged_downtrend",
        "weekly_downtrend",
        "monthly_downtrend",
    }
    lower_lows_without_recovery = (
        structure.get("lower_lows") is True
        and recent["status"] != "improving"
        and technical["status"] != "confirmed_reversal"
    )
    if lower_lows_without_recovery or (
        trend["status"] == "prolonged_downtrend"
        and technical["status"] == "bearish_confirmation"
    ):
        correction_status = "high_risk"
    elif downtrend or structure.get("lower_lows") is True:
        correction_status = "elevated_risk"
    elif recent["status"] == "improving" or structure.get("status") == "recovery_structure":
        correction_status = "recovery_possible"
    else:
        correction_status = "unknown"

    recovery_evidence = [
        recent["status"] == "improving",
        structure.get("status") == "recovery_structure",
        technical["status"] == "confirmed_reversal",
        flow["status"] == "confirmed_positive_flow",
    ]
    if sum(recovery_evidence) >= 2:
        classification = "recovery_candidate"
    elif correction_status in ("high_risk", "elevated_risk"):
        classification = "correction_risk"
    else:
        classification = "inconclusive"

    return {
        "version": 1,
        "classification": classification,
        "trend_context": trend,
        "recent_move_vs_trend": recent,
        "price_structure": structure,
        "technical_reversal": technical,
        "flow_confirmation": flow,
        "lower_lows_without_recovery": {
            "status": "high_risk" if lower_lows_without_recovery else (
                "not_detected" if structure.get("available") else "unknown"
            ),
            "available": structure.get("available", False),
            "detected": lower_lows_without_recovery,
        },
    }