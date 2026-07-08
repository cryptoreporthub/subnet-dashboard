"""
Pathfinder Signal Worker (The Worker)

Responsible for raw data ingestion and pathfinding within the hierarchical,
Mindmap-integrated Engine.
"""

import json
import os
from typing import Any, Dict, Optional

from internal.signals.signal_tracker import SignalTracker


class PathfinderWorker:
    """Discovers signal paths and records them in the pump-cycle tracker."""

    def __init__(self, tracker: SignalTracker = None, soul_map_path: str = None):
        self.tracker = tracker or SignalTracker()
        self.soul_map_path = soul_map_path or os.environ.get(
            "SOUL_MAP_PATH", "data/soul_map.json"
        )
        self._weights: Optional[Dict[str, float]] = None

    def route(self, asset: str, source: str, timestamp: str = None, metadata: dict = None) -> dict:
        """
        Route a discovered signal through the tracker.

        Pathfinder is responsible for identifying which asset/source combinations
        are worth tracking; the SignalTracker owns the pump-cycle state machine.
        """
        return self.tracker.record_signal(asset, source, timestamp, metadata)

    def load_council_weights(self) -> Dict[str, float]:
        """Load learned council weights from the Soul-Map."""
        if self._weights is not None:
            return self._weights
        if os.path.exists(self.soul_map_path):
            try:
                with open(self.soul_map_path, "r") as f:
                    data = json.load(f)
                weights = data.get("adversarial_state", {}).get("council_weights", {})
                if weights:
                    self._weights = weights
                    return self._weights
            except Exception:
                pass
        self._weights = {"quant": 0.4, "hype": 0.3, "dark_horse": 0.3}
        return self._weights

    def weighted_consensus(self, decision: Dict[str, Any]) -> float:
        """
        Recompute a decision's consensus score using learned council weights.

        Falls back to the decision's existing consensus_score if expert
        breakdown data is unavailable.
        """
        breakdown = decision.get("expert_breakdown", {})
        if not breakdown:
            return decision.get("consensus_score", 0.5)

        weights = self.load_council_weights()
        total = 0.0
        weight_sum = 0.0
        for name, weight in weights.items():
            score = breakdown.get(name, {}).get("score", 0.5)
            total += score * weight
            weight_sum += weight

        if weight_sum == 0:
            return decision.get("consensus_score", 0.5)
        return round(total / weight_sum, 4)

    def apply_weights(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy of the decision with consensus_score using learned weights."""
        decision = dict(decision)
        decision["consensus_score"] = self.weighted_consensus(decision)
        return decision
