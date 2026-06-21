"""
Adversarial Judge — scores expert verdicts against actual outcomes.

Phase 0: Price-anchored scoring.
Instead of scoring against registry metadata (emission >= 1.0, social >= 100),
scores against actual_price_delta vs predicted_price_delta.

Score 1.0 if prediction matches reality, 0.0 if opposite direction,
partial credit for correct direction wrong magnitude.

Expert accuracy is computed from price-based outcomes, NOT metadata alignment.
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


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


class AdversarialJudge:
    """
    Scores decisions against outcomes.

    Two scoring modes:
    1. Price-anchored (Phase 0): score against actual price movement
    2. Metadata-based (legacy fallback): score against registry thresholds
    """

    def __init__(
        self,
        persistence_path: str = SOUL_MAP_PATH,
        registry_path: str = REGISTRY_PATH,
        persist: bool = True,
    ):
        self.persistence_path = persistence_path
        self.registry_path = registry_path
        self.persist = persist
        self._soul_map = _load_json(persistence_path)
        self._registry = _load_json(registry_path)

    # ------------------------------------------------------------------
    # Price-anchored scoring (Phase 0)
    # ------------------------------------------------------------------

    def score_prediction(
        self,
        predicted_delta_pct: float,
        actual_delta_pct: float,
        predicted_direction: str,
        actual_direction: str,
    ) -> float:
        """
        Score a prediction against actual price movement.

        predicted_delta_pct: e.g. +5.0 means "predicted +5%"
        actual_delta_pct: e.g. +3.2 means "actually moved +3.2%"
        predicted_direction: "up", "down", or "flat"
        actual_direction: "up", "down", or "flat"

        Returns score 0.0–1.0.
        """
        # Opposite direction → 0.0
        if predicted_direction != actual_direction:
            return 0.0

        # Both flat → 1.0
        if predicted_direction == "flat" and actual_direction == "flat":
            return 1.0

        # Same direction: partial credit based on magnitude accuracy.
        if abs(predicted_delta_pct) < 0.0001:
            return 0.5  # predicted flat but moved

        ratio = min(abs(actual_delta_pct), abs(predicted_delta_pct)) / max(
            abs(actual_delta_pct), abs(predicted_delta_pct)
        )
        # Base score from magnitude accuracy.
        score = 0.5 + 0.5 * ratio

        # Bonus for being within 20% of prediction.
        if ratio >= 0.8:
            score = min(1.0, score + 0.1)

        return round(score, 4)

    def judge_outcome_only(
        self,
        subnet_id: int,
        decision: Dict[str, Any],
        outcome: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Judge a single decision against an outcome.

        If outcome contains price data (actual_price_delta_pct), use
        price-anchored scoring. Otherwise fall back to metadata scoring.
        """
        verdict = {
            "subnet_id": subnet_id,
            "judged_at": _now_iso(),
            "scoring_mode": "metadata",
            "score": 0.0,
            "confidence": 0.0,
            "details": {},
        }

        # Check for price-anchored outcome data.
        if "actual_price_delta_pct" in outcome and "predicted_price_delta_pct" in outcome:
            verdict["scoring_mode"] = "price"
            predicted_delta = float(outcome.get("predicted_price_delta_pct", 0))
            actual_delta = float(outcome.get("actual_price_delta_pct", 0))

            predicted_dir = _direction(predicted_delta)
            actual_dir = _direction(actual_delta)

            score = self.score_prediction(
                predicted_delta, actual_delta, predicted_dir, actual_dir
            )
            verdict["score"] = score
            verdict["confidence"] = score
            verdict["details"] = {
                "predicted_delta_pct": predicted_delta,
                "actual_delta_pct": actual_delta,
                "predicted_direction": predicted_dir,
                "actual_direction": actual_dir,
                "current_price": outcome.get("current_price"),
                "resolution_price": outcome.get("resolution_price"),
            }
            return verdict

        # Fallback: metadata-based scoring.
        return self._judge_metadata(subnet_id, decision, outcome)

    def _judge_metadata(
        self,
        subnet_id: int,
        decision: Dict[str, Any],
        outcome: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Legacy metadata-based scoring (fallback)."""
        action = decision.get("recommended_action", "hold")
        emission = outcome.get("emission", 0.0) or 0.0
        social = outcome.get("social_mentions", 0) or 0
        status = outcome.get("status", "unknown")
        is_overvalued = outcome.get("is_overvalued", False)

        score = 0.5  # neutral baseline

        if action == "accumulate":
            if emission >= 1.0 and social >= 100 and status == "active" and not is_overvalued:
                score = 0.85
            elif emission >= 0.5 and social >= 50:
                score = 0.6
            else:
                score = 0.3
        elif action == "reduce":
            if is_overvalued or status in ("at-risk", "deprecated"):
                score = 0.85
            elif emission < 0.3 or social < 50:
                score = 0.7
            else:
                score = 0.4
        elif action == "hold":
            if status == "active" and not is_overvalued:
                score = 0.7
            else:
                score = 0.5

        return {
            "subnet_id": subnet_id,
            "judged_at": _now_iso(),
            "scoring_mode": "metadata",
            "score": score,
            "confidence": score,
            "details": {
                "emission": emission,
                "social_mentions": social,
                "status": status,
                "is_overvalued": is_overvalued,
            },
        }

    def judge_decision(
        self,
        decision: Dict[str, Any],
        registry_item: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Judge a decision against registry metadata.
        Used by the SimiVision trace endpoint.
        """
        action = decision.get("recommended_action", "hold")
        emission = registry_item.get("emission", 0.0) or 0.0
        social = registry_item.get("social_mentions", 0) or 0
        status = registry_item.get("status", "unknown")
        is_overvalued = registry_item.get("is_overvalued", False)

        return self._judge_metadata(
            0,
            decision,
            {
                "emission": emission,
                "social_mentions": social,
                "status": status,
                "is_overvalued": is_overvalued,
            },
        )

    # ------------------------------------------------------------------
    # Council weights & expert track records
    # ------------------------------------------------------------------

    def get_council_weights(self) -> Dict[str, float]:
        """Return current expert council weights."""
        return self._soul_map.get("expert_weights", {
            "quant": 0.25,
            "hype": 0.25,
            "contrarian": 0.25,
            "technical": 0.25,
        })

    def get_expert_track_records(self) -> Dict[str, Any]:
        """Return expert accuracy track records."""
        return self._soul_map.get("expert_track_records", {
            "quant": {"correct": 0, "total": 0, "accuracy": 0.5},
            "hype": {"correct": 0, "total": 0, "accuracy": 0.5},
            "contrarian": {"correct": 0, "total": 0, "accuracy": 0.5},
            "technical": {"correct": 0, "total": 0, "accuracy": 0.5},
        })

    def get_learning_trail(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return recent verdicts as a learning trail."""
        verdicts = self._soul_map.get("verdicts", [])
        return verdicts[-limit:]

    def update_expert_accuracy(
        self,
        expert_name: str,
        was_correct: bool,
    ) -> None:
        """Update an expert's track record based on outcome."""
        records = self.get_expert_track_records()
        if expert_name not in records:
            records[expert_name] = {"correct": 0, "total": 0, "accuracy": 0.5}
        records[expert_name]["total"] += 1
        if was_correct:
            records[expert_name]["correct"] += 1
        total = records[expert_name]["total"]
        correct = records[expert_name]["correct"]
        records[expert_name]["accuracy"] = round(correct / total, 4) if total > 0 else 0.5
        self._soul_map["expert_track_records"] = records
        if self.persist:
            self._persist()

    def record_verdict(self, verdict: Dict[str, Any]) -> None:
        """Record a verdict in the learning trail."""
        verdicts = self._soul_map.get("verdicts", [])
        verdicts.append(verdict)
        # Keep last 500 verdicts.
        if len(verdicts) > 500:
            verdicts = verdicts[-500:]
        self._soul_map["verdicts"] = verdicts
        if self.persist:
            self._persist()

    def _persist(self) -> None:
        _save_json(self.persistence_path, self._soul_map)


def _direction(delta_pct: float) -> str:
    if delta_pct > 0.005:
        return "up"
    elif delta_pct < -0.005:
        return "down"
    return "flat"