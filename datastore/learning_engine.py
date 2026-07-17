"""
Learning Engine for Subnet Dashboard

Thin wrapper around the live Council weight system (quant/hype/dark_horse/technical)
and the prediction resolver. Keeps the ``LearningEngine`` class name and the
feedback router API so server.py stays compatible.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from internal.council import resolver, scenario_memory, rotation_tracker
from internal.council.weights import load_weights, save_weights

logger = logging.getLogger(__name__)

CANONICAL_EXPERTS = {"quant", "hype", "dark_horse", "technical"}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

class LearningEngine:
    """Manages the learning loop for expert council weights."""

    def __init__(self, soul_map_path: str = "data/soul_map.json"):
        self.soul_map_path = soul_map_path

    def save_soul_map(self, soul_map: Dict[str, Any]) -> None:
        """Persist a soul-map payload for backward compatibility."""
        import json
        import os
        os.makedirs(os.path.dirname(self.soul_map_path) or ".", exist_ok=True)
        with open(self.soul_map_path, "w", encoding="utf-8") as fh:
            json.dump(soul_map, fh, indent=2)

    def load_soul_map(self) -> Dict[str, Any]:
        """Return a dict with live expert weights and resolver performance history."""
        weights = load_weights(self.soul_map_path)
        resolved = resolver.get_resolved_predictions()
        return {
            "expert_weights": weights,
            "performance_history": {
                "accuracy": resolved.get("stats", {}).get("accuracy", 0.0),
                "total_records": resolved.get("stats", {}).get("total", 0),
                "correct": resolved.get("stats", {}).get("correct", 0),
                "wrong": resolved.get("stats", {}).get("wrong", 0),
                "pending": resolved.get("stats", {}).get("pending", 0),
            },
        }

    def get_stats(self) -> Dict[str, Any]:
        """Return current learning stats (weights + resolver state)."""
        weights = load_weights(self.soul_map_path)
        resolved = resolver.get_resolved_predictions()
        stats = resolved.get("stats", {})
        return {
            "expert_weights": weights,
            "accuracy": stats.get("accuracy", 0.0),
            "total_records": stats.get("total", 0),
            "last_updated": _now_iso(),
            "pending": stats.get("pending", 0),
            "resolved": stats.get("correct", 0) + stats.get("wrong", 0),
        }

    def record_feedback(
        self,
        subnet_id: int,
        recommendation: str,
        actual_performance: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Record the outcome of a prediction and nudge the relevant expert weight."""
        actual_performance = actual_performance or {}
        correct = bool(actual_performance.get("correct_prediction", False))

        expert = self._normalize_recommendation(recommendation)
        if expert:
            from internal.council.weights import nudge_expert

            nudge_expert(expert, correct, self.soul_map_path)

        try:
            scenario_memory.add_scenario(
                name=f"feedback_subnet_{subnet_id}",
                features={
                    "subnet_id": subnet_id,
                    "recommendation": recommendation,
                    "correct": correct,
                    **{
                        k: v
                        for k, v in actual_performance.items()
                        if k not in {"correct_prediction"}
                    },
                },
                outcome="correct" if correct else "wrong",
            )
        except Exception as exc:
            logger.warning(f"Could not log feedback scenario: {exc}")

        return {
            "status": "feedback recorded",
            "success": True,
            "expert": expert,
            "correct": correct,
            "timestamp": _now_iso(),
        }

    @staticmethod
    def _normalize_recommendation(recommendation: Optional[str]) -> Optional[str]:
        """Map a recommendation/action/signal to a canonical Council expert."""
        if not isinstance(recommendation, str):
            return None
        rec = recommendation.lower().strip()
        if rec in CANONICAL_EXPERTS:
            return rec
        if any(k in rec for k in ("dark", "horse", "onchain", "on-chain", "flow")):
            return "dark_horse"
        if any(k in rec for k in ("whale", "momentum", "hype", "social")):
            return "hype"
        if any(k in rec for k in ("rsi", "macd", "technical", "indicator")):
            return "technical"
        if any(k in rec for k in ("quant", "fundamental", "yield", "emission")):
            return "quant"
        # Legacy: map contrarian to dark_horse for backward compatibility
        if "contrarian" in rec:
            return "dark_horse"
        return None

def create_feedback_router():
    """Build a FastAPI APIRouter exposing the self-learning feedback loop."""
    from fastapi import APIRouter, Request, HTTPException

    router = APIRouter()

    @router.post("/api/feedback")
    async def record_feedback(request: Request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        data = data or {}
        subnet_id = data.get("subnet_id")
        recommendation = data.get("recommendation")
        actual_performance = data.get("actual_performance", {})

        if not subnet_id or not recommendation:
            raise HTTPException(
                status_code=400, detail="Missing subnet_id or recommendation"
            )

        engine = LearningEngine()
        return engine.record_feedback(subnet_id, recommendation, actual_performance)

    return router

def create_feedback_endpoint(server_module):
    """Legacy registration hook (kept for backward compatibility)."""
    router = create_feedback_router()
    if hasattr(server_module, "include_router"):
        server_module.include_router(router)
    return router
