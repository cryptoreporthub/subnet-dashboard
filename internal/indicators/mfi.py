"""Money Flow Index (MFI) computation."""
from typing import Any, Dict, List


def compute_mfi(
    candles: List[Dict[str, Any]],
    period: int = 14,
) -> Dict[str, Any]:
    """
    Compute Money Flow Index from OHLCV candles.

    Returns MFI value and overbought/oversold flags.
    """
    if len(candles) < period + 1:
        return {
            "mfi": 50.0,
            "overbought": False,
            "oversold": False,
            "neutral": True,
        }

    typical_prices = [(c["high"] + c["low"] + c["close"]) / 3.0 for c in candles]
    volumes = [c["volume"] for c in candles]

    pos_flow, neg_flow = 0.0, 0.0
    for i in range(len(candles) - period, len(candles)):
        rmf = typical_prices[i] * volumes[i]
        if i > 0 and typical_prices[i] > typical_prices[i - 1]:
            pos_flow += rmf
        elif i > 0 and typical_prices[i] < typical_prices[i - 1]:
            neg_flow += rmf

    if neg_flow == 0:
        mfi = 100.0 if pos_flow > 0 else 50.0
    else:
        mfi = 100.0 - (100.0 / (1.0 + pos_flow / neg_flow))

    return {
        "mfi": round(mfi, 4),
        "overbought": mfi > 80.0,
        "oversold": mfi < 20.0,
        "neutral": 20.0 <= mfi <= 80.0,
    }