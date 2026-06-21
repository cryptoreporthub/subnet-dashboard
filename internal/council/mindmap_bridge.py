"""
MindmapBridge — connects the Council to the Soul-Map persistence layer.

Phase 0: get_brain_recommendations() now derives recommendations from
outcome history — what actually predicted price movement — instead of
hardcoded emission/social thresholds.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.conviction_decay import apply_decay_to_nodes, node_metadata

SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_json(path: str, data: Dict[str, Any]) -> None:
    dir_name = os.path.dirname(path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp, path)


class MindmapBridge:
    """
    Bridge between the Council's decisions and the Soul-Map persistence.

    Provides:
    - Brain recommendations derived from outcome history
    - SimiVision feedback logging
    - Soul-map state management
    - Conviction decay integration
    """

    def __init__(
        self,
        persistence_path: str = SOUL_MAP_PATH,
        registry_path: str = REGISTRY_PATH,
    ):
        self.persistence_path = persistence_path
        self.registry_path = registry_path
        self._soul_map = _load_json(persistence_path)
        self._registry = _load_json(registry_path)

    @property
    def soul_map_state(self) -> Dict[str, Any]:
        return self._soul_map.get("soul_map_state", {})

    # ------------------------------------------------------------------
    # Brain Recommendations (Phase 0: outcome-driven)
    # ------------------------------------------------------------------

    def get_brain_recommendations(self) -> Dict[str, Any]:
        """
        Return Brain recommendations for all subnets.

        Phase 0: recommendations are derived from outcome history —
        subnets with correct predictions get accumulate, wrong get reduce,
        no history gets hold.

        Falls back to metadata-based recommendations if no outcome
        history exists.
        """
        verdicts = self._soul_map.get("verdicts", [])
        registry = self._registry or _load_json(self.registry_path)

        # Build per-subnet outcome stats.
        subnet_stats: Dict[str, Dict[str, Any]] = {}
        for v in verdicts:
            sid = str(v.get("subnet_id", ""))
            if not sid:
                continue
            if sid not in subnet_stats:
                subnet_stats[sid] = {"total": 0, "sum_score": 0.0, "correct": 0}
            subnet_stats[sid]["total"] += 1
            score = v.get("score", 0.0) or 0.0
            subnet_stats[sid]["sum_score"] += score
            if score >= 0.7:
                subnet_stats[sid]["correct"] += 1

        recommendations: Dict[str, Dict[str, Any]] = {}

        for sid, item in registry.items():
            stats = subnet_stats.get(sid)
            if stats and stats["total"] > 0:
                avg_score = stats["sum_score"] / stats["total"]
                correct_ratio = stats["correct"] / stats["total"]

                if correct_ratio >= 0.6:
                    action = "accumulate"
                    target_weight = min(0.9, 0.5 + correct_ratio * 0.4)
                elif avg_score < 0.3:
                    action = "reduce"
                    target_weight = 0.1
                else:
                    action = "hold"
                    target_weight = 0.5

                recommendations[sid] = {
                    "action": action,
                    "target_weight": round(target_weight, 2),
                    "status": item.get("status", "unknown"),
                    "metrics": {
                        "emission": item.get("emission"),
                        "social_mentions": item.get("social_mentions"),
                        "is_overvalued": item.get("is_overvalued"),
                        "emission_rank": item.get("emission_rank"),
                        "staking_data": item.get("staking_data"),
                    },
                    "outcome_stats": {
                        "total_verdicts": stats["total"],
                        "avg_score": round(avg_score, 4),
                        "correct_ratio": round(correct_ratio, 4),
                    },
                }
            else:
                # Fallback: metadata-based recommendation.
                emission = item.get("emission", 0.0) or 0.0
                social = item.get("social_mentions", 0) or 0
                is_overvalued = item.get("is_overvalued", False)
                status = item.get("status", "unknown")

                if status in ("deprecated", "at-risk") or is_overvalued:
                    action = "reduce"
                    target_weight = 0.1
                elif emission > 1.5 and social > 1000:
                    action = "accumulate"
                    target_weight = 0.8
                elif emission > 0.5 and social > 100:
                    action = "accumulate"
                    target_weight = 0.6
                else:
                    action = "hold"
                    target_weight = 0.5

                recommendations[sid] = {
                    "action": action,
                    "target_weight": target_weight,
                    "status": status,
                    "metrics": {
                        "emission": emission,
                        "social_mentions": social,
                        "is_overvalued": is_overvalued,
                        "emission_rank": item.get("emission_rank"),
                        "staking_data": item.get("staking_data"),
                    },
                }

        return {"recommendations": recommendations}

    # ------------------------------------------------------------------
    # SimiVision feedback
    # ------------------------------------------------------------------

    def log_simivision_feedback(
        self, subnet_id: int, outcome: int, note: str = ""
    ) -> Dict[str, Any]:
        """Record user feedback on a SimiVision pick."""
        entry = {
            "subnet_id": subnet_id,
            "outcome": outcome,
            "note": note,
            "timestamp": _now_iso(),
        }
        logs = self._soul_map.get("feedback_logs", [])
        logs.append(entry)
        self._soul_map["feedback_logs"] = logs
        _save_json(self.persistence_path, self._soul_map)
        return entry

    def get_simivision_feedback_boost(self, subnet_id: int) -> float:
        """Compute a feedback boost from user feedback history."""
        logs = self._soul_map.get("feedback_logs", [])
        relevant = [
            l for l in logs
            if l.get("subnet_id") == subnet_id and l.get("outcome") is not None
        ]
        if not relevant:
            return 0.0
        recent = relevant[-5:]
        boost = sum(r.get("outcome", 0) for r in recent) / len(recent) * 0.1
        return round(boost, 4)

    def log_simivision_picks(self, picks: List[Dict[str, Any]]) -> None:
        """Log the current SimiVision picks for change detection."""
        state = self._soul_map.get("soul_map_state", {})
        state["last_simivision_picks"] = {
            "picks": picks,
            "timestamp": _now_iso(),
        }
        self._soul_map["soul_map_state"] = state
        _save_json(self.persistence_path, self._soul_map)

    # ------------------------------------------------------------------
    # Conviction decay integration
    # ------------------------------------------------------------------

    def get_active_nodes(self) -> Dict[str, Any]:
        """Return active (non-pruned) nodes after applying conviction decay."""
        nodes = self._soul_map.get("mindmap_nodes", [])
        result = apply_decay_to_nodes(nodes)
        # Persist pruned state.
        self._soul_map["mindmap_nodes"] = result["active"] + result["pruned"]
        _save_json(self.persistence_path, self._soul_map)
        return result

    def add_node(
        self,
        signal_type: str,
        data: Dict[str, Any],
        outcome_score: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Add a new node to the Mindmap with decay metadata."""
        meta = node_metadata(signal_type, outcome_score)
        node = {**meta, **data}
        nodes = self._soul_map.get("mindmap_nodes", [])
        nodes.append(node)
        self._soul_map["mindmap_nodes"] = nodes
        _save_json(self.persistence_path, self._soul_map)
        return node

    # ------------------------------------------------------------------
    # Hypothesis management (Phase 0)
    # ------------------------------------------------------------------

    def record_hypothesis(
        self,
        subnet_id: int,
        prediction: str,
        predicted_delta_pct: float,
        horizon_iso: str,
        current_price: float,
        sources: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Record a testable hypothesis with prediction and horizon."""
        hypothesis = {
            "subnet_id": subnet_id,
            "prediction": prediction,
            "predicted_delta_pct": predicted_delta_pct,
            "horizon": horizon_iso,
            "current_price": current_price,
            "sources": sources or [],
            "recorded_at": _now_iso(),
            "resolved": False,
        }
        hypotheses = self._soul_map.get("hypotheses", [])
        hypotheses.append(hypothesis)
        self._soul_map["hypotheses"] = hypotheses
        _save_json(self.persistence_path, self._soul_map)
        return hypothesis

    def resolve_hypothesis(
        self,
        subnet_id: int,
        resolution_price: float,
    ) -> Optional[Dict[str, Any]]:
        """Resolve the latest unresolved hypothesis for a subnet."""
        hypotheses = self._soul_map.get("hypotheses", [])
        for h in reversed(hypotheses):
            if h.get("subnet_id") == subnet_id and not h.get("resolved"):
                actual_delta_pct = (
                    (resolution_price - h["current_price"]) / h["current_price"] * 100
                    if h["current_price"] > 0
                    else 0.0
                )
                h["resolved"] = True
                h["resolution_price"] = resolution_price
                h["actual_delta_pct"] = round(actual_delta_pct, 4)
                h["resolved_at"] = _now_iso()

                # Score the prediction.
                predicted_dir = _direction(h["predicted_delta_pct"])
                actual_dir = _direction(actual_delta_pct)
                if predicted_dir == actual_dir:
                    ratio = (
                        min(abs(actual_delta_pct), abs(h["predicted_delta_pct"]))
                        / max(abs(actual_delta_pct), abs(h["predicted_delta_pct"]))
                        if max(abs(actual_delta_pct), abs(h["predicted_delta_pct"])) > 0
                        else 1.0
                    )
                    h["outcome_score"] = round(0.5 + 0.5 * ratio, 4)
                else:
                    h["outcome_score"] = 0.0

                _save_json(self.persistence_path, self._soul_map)
                return h
        return None

    def get_pending_hypotheses(self) -> List[Dict[str, Any]]:
        """Return all unresolved hypotheses."""
        return [h for h in self._soul_map.get("hypotheses", []) if not h.get("resolved")]


def _direction(delta_pct: float) -> str:
    if delta_pct > 0.005:
        return "up"
    elif delta_pct < -0.005:
        return "down"
    return "flat"