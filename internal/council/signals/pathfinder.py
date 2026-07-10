"""
Pathfinder Signal Worker (The Worker)

Responsible for raw data ingestion and pathfinding within the hierarchical,
Mindmap-integrated Engine.
"""

from typing import Any, Dict


class PathfinderWorker:
    def __init__(self, tracker=None):
        self.tracker = tracker
        self._weights: Dict[str, float] = {}

    def apply_weights(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """Recompute consensus using learned council weights."""
        breakdown = decision.get("expert_breakdown", {})
        weights = self._weights or {name: 1.0 for name in breakdown}
        total_w = 0.0
        weighted = 0.0
        for name, opinion in breakdown.items():
            if not isinstance(opinion, dict):
                continue
            w = float(weights.get(name, 1.0))
            score = float(opinion.get("score", 0.5))
            weighted += score * w
            total_w += w
        adjusted = dict(decision)
        adjusted["consensus_score"] = round(weighted / total_w, 4) if total_w else 0.5
        adjusted.setdefault("brain", decision.get("brain", {}))
        return adjusted

    def route(self, asset: str, source: str = "pathfinder"):
        if self.tracker and hasattr(self.tracker, "record_signal"):
            return self.tracker.record_signal(asset, source)
        return None