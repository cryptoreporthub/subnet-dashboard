"""Detect significant indicator crossover events."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event(
    event_type: str,
    signal_type: str,
    direction: str,
    strength: float,
    description: str,
    indicator_value: float,
    threshold: float,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "event_type": event_type,
        "signal_type": signal_type,
        "direction": direction,
        "strength": round(strength, 4),
        "description": description,
        "indicator_value": round(indicator_value, 4),
        "threshold": round(threshold, 4),
        "timestamp": timestamp or _now_iso(),
    }


def detect_crossovers(
    rsi_result: Dict[str, Any],
    macd_result: Dict[str, Any],
    momentum_result: Dict[str, Any],
    prev_rsi: Optional[Dict[str, Any]] = None,
    prev_macd: Optional[Dict[str, Any]] = None,
    prev_momentum: Optional[Dict[str, Any]] = None,
    timestamp: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Detect crossover events from RSI, MACD, and momentum outputs.

    Uses previous indicator results to confirm threshold crosses.
    """
    events: List[Dict[str, Any]] = []

    rsi = rsi_result or {}
    macd = macd_result or {}
    mom = momentum_result or {}

    rsi_prev = prev_rsi or {}
    macd_prev = prev_macd or {}
    mom_prev = prev_momentum or {}

    # RSI oversold reversal: was below 30, now above 30.
    if rsi.get("rsi", 50) > 30.0 and rsi_prev.get("rsi", 50) <= 30.0:
        strength = min(1.0, (rsi.get("rsi", 30) - 30.0) / 10.0)
        events.append(
            _event(
                event_type="rsi_oversold_reversal",
                signal_type="rsi_crossover",
                direction="bullish",
                strength=strength,
                description=f"RSI crossed above 30 from {rsi_prev.get('rsi', 30)} to {rsi.get('rsi', 30)} — oversold reversal",
                indicator_value=rsi.get("rsi", 30),
                threshold=30.0,
                timestamp=timestamp,
            )
        )

    # RSI overbought reversal: was above 70, now below 70.
    if rsi.get("rsi", 50) < 70.0 and rsi_prev.get("rsi", 50) >= 70.0:
        strength = min(1.0, (70.0 - rsi.get("rsi", 70)) / 10.0)
        events.append(
            _event(
                event_type="rsi_overbought_reversal",
                signal_type="rsi_crossover",
                direction="bearish",
                strength=strength,
                description=f"RSI crossed below 70 from {rsi_prev.get('rsi', 70)} to {rsi.get('rsi', 70)} — overbought reversal",
                indicator_value=rsi.get("rsi", 70),
                threshold=70.0,
                timestamp=timestamp,
            )
        )

    # MACD bullish cross: histogram negative to positive.
    if macd.get("bullish_cross"):
        events.append(
            _event(
                event_type="macd_bullish_cross",
                signal_type="macd_cross",
                direction="bullish",
                strength=min(1.0, abs(macd.get("histogram", 0)) / 0.01 + 0.5),
                description=f"MACD histogram crossed from negative to positive ({macd.get('histogram', 0)})",
                indicator_value=macd.get("histogram", 0),
                threshold=0.0,
                timestamp=timestamp,
            )
        )

    # MACD bearish cross: histogram positive to negative.
    if macd.get("bearish_cross"):
        events.append(
            _event(
                event_type="macd_bearish_cross",
                signal_type="macd_cross",
                direction="bearish",
                strength=min(1.0, abs(macd.get("histogram", 0)) / 0.01 + 0.5),
                description=f"MACD histogram crossed from positive to negative ({macd.get('histogram', 0)})",
                indicator_value=macd.get("histogram", 0),
                threshold=0.0,
                timestamp=timestamp,
            )
        )

    # Stochastic oversold reversal: %K crossed above %D while both below 20.
    k = mom.get("stochastic_k", 50)
    k_prev = mom_prev.get("stochastic_k", k)
    d = mom.get("stochastic_d", 50)
    d_prev = mom_prev.get("stochastic_d", d)
    if k > d and k_prev <= d_prev and k < 20.0 and d < 20.0:
        events.append(
            _event(
                event_type="stochastic_oversold_reversal",
                signal_type="stochastic_reversal",
                direction="bullish",
                strength=min(1.0, (20.0 - k) / 10.0 + 0.3),
                description=f"Stochastic %K crossed above %D while both below 20 (K={k}, D={d})",
                indicator_value=k,
                threshold=20.0,
                timestamp=timestamp,
            )
        )

    # Momentum shift: ROC crossed zero.
    roc = mom.get("roc", 0)
    roc_prev = mom_prev.get("roc", roc)
    if roc_prev < 0 <= roc:
        events.append(
            _event(
                event_type="momentum_shift",
                signal_type="momentum_shift",
                direction="bullish",
                strength=min(1.0, abs(roc) / 5.0 + 0.3),
                description=f"Rate of change crossed above zero from {roc_prev} to {roc}",
                indicator_value=roc,
                threshold=0.0,
                timestamp=timestamp,
            )
        )
    elif roc_prev > 0 >= roc:
        events.append(
            _event(
                event_type="momentum_shift",
                signal_type="momentum_shift",
                direction="bearish",
                strength=min(1.0, abs(roc) / 5.0 + 0.3),
                description=f"Rate of change crossed below zero from {roc_prev} to {roc}",
                indicator_value=roc,
                threshold=0.0,
                timestamp=timestamp,
            )
        )

    # Williams %R oversold exit: crossed above -80 from below.
    w = mom.get("williams_r", -50)
    w_prev = mom_prev.get("williams_r", w)
    if w > -80.0 and w_prev <= -80.0:
        events.append(
            _event(
                event_type="williams_oversold_exit",
                signal_type="stochastic_reversal",
                direction="bullish",
                strength=min(1.0, (w + 80.0) / 10.0 + 0.3),
                description=f"Williams %R crossed above -80 from {w_prev} to {w}",
                indicator_value=w,
                threshold=-80.0,
                timestamp=timestamp,
            )
        )

    return events
