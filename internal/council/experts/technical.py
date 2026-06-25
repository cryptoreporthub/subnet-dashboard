"""Technical Expert — 4th council expert driven by indicator signals."""

from typing import Any, Dict, List, Optional


class TechnicalExpert:
    """Reads indicator state from context and returns a 0-1 score."""

    def analyze(self, subnet_id: int, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        context = context or {}
        indicator_state = context.get("indicator_state", {})
        active_signals = indicator_state.get("active_signals", [])

        score = 0.5
        signal = "hold"
        reasons: List[str] = []

        bullish_signals = {
            "rsi_oversold_reversal",
            "macd_bullish_cross",
            "stochastic_oversold_reversal",
            "williams_oversold_exit",
            "momentum_shift",
        }
        bearish_signals = {
            "rsi_overbought_reversal",
            "macd_bearish_cross",
        }

        bullish_count = sum(1 for s in active_signals if s in bullish_signals)
        bearish_count = sum(1 for s in active_signals if s in bearish_signals)

        macd_hist = indicator_state.get("macd_histogram", 0) or 0
        stochastic_k = indicator_state.get("stochastic_k", 50) or 50

        if bullish_count > 0:
            score = 0.7 + min(0.2, bullish_count * 0.05)
            signal = "buy"
            reasons.append(f"{bullish_count} bullish indicator signal(s)")
        if bearish_count > 0:
            score = 0.3 - min(0.2, bearish_count * 0.05)
            signal = "sell"
            reasons.append(f"{bearish_count} bearish indicator signal(s)")

        if macd_hist > 0:
            score += 0.05
            reasons.append("positive MACD histogram")
        elif macd_hist < 0:
            score -= 0.05
            reasons.append("negative MACD histogram")

        if stochastic_k < 20:
            score += 0.05
            reasons.append("stochastic oversold")
        elif stochastic_k > 80:
            score -= 0.05
            reasons.append("stochastic overbought")

        score = round(min(1.0, max(0.0, score)), 4)

        return {
            "expert": "technical",
            "subnet_id": subnet_id,
            "score": score,
            "signal": signal,
            "metrics": {
                "active_signals": active_signals,
                "bullish_count": bullish_count,
                "bearish_count": bearish_count,
                "macd_histogram": macd_hist,
                "stochastic_k": stochastic_k,
                "reasons": reasons,
            },
        }
