"""
Selector — weights expert opinions and produces consensus decisions.

The Selector takes a set of subnet IDs and context, runs them through
the multi-expert council (Quant, Hype, Contrarian, Technical), and
produces weighted consensus decisions.
"""

from typing import Any, Dict, List, Optional

from internal.council.mindmap_bridge import MindmapBridge


class Selector:
    """
    Multi-expert council selector.

    Weights expert opinions and produces consensus decisions for each
    subnet in the daily rotation.
    """

    def __init__(self, mindmap_bridge: Optional[MindmapBridge] = None):
        self.bridge = mindmap_bridge or MindmapBridge()

    def process_daily_rotation(
        self,
        subnet_ids: List[int],
        context_map: Optional[Dict[int, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Process a daily rotation of subnet evaluations.

        Returns:
            {
                "daily_output": {
                    "date": "...",
                    "decisions": [...],
                }
            }
        """
        context_map = context_map or {}
        decisions = []

        for sid in subnet_ids:
            ctx = context_map.get(sid, {})
            decision = self._evaluate_subnet(sid, ctx)
            decisions.append(decision)

        return {
            "daily_output": {
                "date": self._today(),
                "decisions": decisions,
            }
        }

    def _evaluate_subnet(
        self, sid: int, ctx: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Evaluate a single subnet through the expert council."""
        emission = ctx.get("emission", 0.0) or 0.0
        social = ctx.get("social_mentions", 0) or 0
        is_overvalued = ctx.get("is_overvalued", False)

        # Quant expert: emission-driven.
        if emission > 1.0:
            quant_score = 0.85
            emission_stability = "high"
        elif emission < 0.2:
            quant_score = 0.4
            emission_stability = "low"
        else:
            quant_score = 0.75
            emission_stability = "medium"

        # Hype expert: social-driven.
        if social > 1000:
            hype_score = 0.9
            sentiment = "bullish"
        elif social < 100:
            hype_score = 0.3
            sentiment = "bearish"
        else:
            hype_score = 0.65
            sentiment = "neutral"

        # Contrarian expert: inverse overvaluation.
        contrarian_score = 0.2 if is_overvalued else 0.8
        contrarian_signal = "sell" if is_overvalued else "buy"

        # Technical expert: neutral baseline (no price data).
        technical_score = 0.5
        technical_signal = "hold"

        breakdown = {
            "quant": {
                "score": quant_score,
                "metrics": {
                    "emission_stability": emission_stability,
                    "performance_index": quant_score * 100,
                },
            },
            "hype": {
                "score": hype_score,
                "sentiment": sentiment,
                "metrics": {
                    "social_volume": social,
                    "hype_index": hype_score * 100,
                },
            },
            "contrarian": {
                "score": contrarian_score,
                "signal": contrarian_signal,
                "metrics": {"contrarian_index": contrarian_score * 100},
            },
            "technical": {
                "score": technical_score,
                "signal": technical_signal,
                "metrics": {
                    "active_signals": [],
                    "bullish_count": 0,
                    "bearish_count": 0,
                    "macd_histogram": 0,
                    "stochastic_k": 50,
                    "reasons": [],
                },
            },
        }

        # Weighted consensus.
        weights = self.bridge._soul_map.get("expert_weights", {
            "quant": 0.25,
            "hype": 0.25,
            "contrarian": 0.25,
            "technical": 0.25,
        })
        consensus = (
            quant_score * weights.get("quant", 0.25)
            + hype_score * weights.get("hype", 0.25)
            + contrarian_score * weights.get("contrarian", 0.25)
            + technical_score * weights.get("technical", 0.25)
        )

        if consensus >= 0.7:
            action = "accumulate"
        elif consensus <= 0.4:
            action = "reduce"
        else:
            action = "hold"

        return {
            "subnet_id": sid,
            "consensus_score": round(consensus, 4),
            "recommended_action": action,
            "expert_breakdown": breakdown,
        }

    @staticmethod
    def _today() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")