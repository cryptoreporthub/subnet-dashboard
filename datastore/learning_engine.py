"""
Learning Engine for Subnet Dashboard

Read-only view over the live Council weight system (quant/hype/dark_horse/technical)
and the prediction resolver. Weights change only through the resolver's graded
outcomes (``internal.council.resolver``) and the calibration pipeline; nothing here
writes learning state.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from internal.council import resolver
from internal.council.weights import load_weights

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

class LearningEngine:
    """Read-only learning stats and soul-map view."""

    def __init__(self, soul_map_path: str = "data/soul_map.json"):
        self.soul_map_path = soul_map_path

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
