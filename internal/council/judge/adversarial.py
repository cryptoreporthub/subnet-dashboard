"""
Adversarial Judge (The Feedback Loop)

Outcome-driven adversarial intelligence layer for the SimiVision council.

Responsibilities:
- Score selector decisions against observed outcomes.
- Persist verdicts and maintain a learning trail in the Soul-Map.
- Track per-expert accuracy and update adaptive council weights.
- Surface verdict confidence and expert track records for the UI/API.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class AdversarialJudge:
    """
    Compares predictions against actual outcomes and updates the Soul-Map
    with verdicts, expert track records, and adaptive council weights.
    """

    DEFAULT_WEIGHTS = {"quant": 0.4, "hype": 0.3, "contrarian": 0.3}
    EXPERT_NAMES = ("quant", "hype", "contrarian")

    def __init__(
        self,
        persistence_path: str = "data/soul_map.json",
        registry_path: str = "config/registry.json",
        persist: bool = False,
    ):
        self.persistence_path = persistence_path
        self.registry_path = registry_path
        self.persist = persist
        self._state: Dict[str, Any] = {}
        self._load_state()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def _load_state(self) -> None:
        if os.path.exists(self.persistence_path):
            try:
                with open(self.persistence_path, "r") as f:
                    data = json.load(f)
                self._state = data.get("adversarial_state", {})
            except Exception:
                self._state = {}
        self._state.setdefault("council_weights", dict(self.DEFAULT_WEIGHTS))
        self._state.setdefault("expert_track_records", {})
        self._state.setdefault("verdicts", [])
        self._state.setdefault("learning_trail", [])

    def _save_state(self) -> None:
        dir_name = os.path.dirname(self.persistence_path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)

        data: Dict[str, Any] = {}
        if os.path.exists(self.persistence_path):
            try:
                with open(self.persistence_path, "r") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        data["adversarial_state"] = self._state
        temp_path = self.persistence_path + ".tmp"
        with open(temp_path, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, self.persistence_path)

    # ------------------------------------------------------------------
    # Public accessors used by SimiVision and the API
    # ------------------------------------------------------------------
    def get_council_weights(self) -> Dict[str, float]:
        return dict(self._state.get("council_weights", self.DEFAULT_WEIGHTS))

    def get_expert_track_records(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._state.get("expert_track_records", {}))

    def get_learning_trail(self, limit: int = 50) -> List[Dict[str, Any]]:
        trail = self._state.get("learning_trail", [])
        return trail[-limit:]

    def get_verdicts(
        self, subnet_id: Optional[int] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        verdicts = self._state.get("verdicts", [])
        if subnet_id is not None:
            verdicts = [v for v in verdicts if v.get("subnet_id") == subnet_id]
        return verdicts[-limit:]

    # ------------------------------------------------------------------
    # Core judgement logic
    # ------------------------------------------------------------------
    def judge_decision(
        self,
        decision: Dict[str, Any],
        outcome: Dict[str, Any],
        subnet_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Score a selector decision against observed outcome data.

        Returns a verdict dict with score, confidence, action, note,
        outcome label, expert contributions, and timestamp.
        """
        decision = decision or {}
        outcome = outcome or {}
        action = decision.get("recommended_action", "hold")
        status = outcome.get("status", "unknown")
        emission = outcome.get("emission", 0.0) or 0.0
        social = outcome.get("social_mentions", 0) or 0
        is_overvalued = outcome.get("is_overvalued", False)
        subnet_id = subnet_id or decision.get("subnet_id")

        # Determine outcome validation and base verdict score.
        if action == "accumulate":
            if (
                status == "active"
                and emission >= 1.0
                and social >= 100
                and not is_overvalued
            ):
                score = 1.0
                outcome_label = "validated"
                note = "Accumulate validated by active status, strong emission, and social signal."
            elif status in ("deprecated", "at-risk") or is_overvalued:
                score = 0.0
                outcome_label = "contradicted"
                note = "Accumulate contradicted by risk flags or overvaluation."
            else:
                score = 0.5
                outcome_label = "neutral"
                note = "Accumulate has mixed support from observed outcome."
        elif action == "reduce":
            if is_overvalued or status in ("deprecated", "at-risk") or emission < 0.5:
                score = 1.0
                outcome_label = "validated"
                note = "Reduce validated by overvaluation, risk status, or weak emission."
            elif emission >= 1.0 and social >= 1000 and not is_overvalued:
                score = 0.0
                outcome_label = "contradicted"
                note = "Reduce contradicted by strong emission and social momentum."
            else:
                score = 0.5
                outcome_label = "neutral"
                note = "Reduce has mixed support from observed outcome."
        else:
            score = 0.5
            outcome_label = "neutral"
            note = "Hold is a neutral verdict."

        # Build expert contributions using current adaptive weights.
        weights = self.get_council_weights()
        breakdown = decision.get("expert_breakdown", {})
        expert_contributions: Dict[str, Dict[str, Any]] = {}
        for name in self.EXPERT_NAMES:
            expert = breakdown.get(name, {})
            expert_score = expert.get("score", 0.5)
            expert_contributions[name] = {
                "score": expert_score,
                "weight": weights.get(name, self.DEFAULT_WEIGHTS[name]),
                "accuracy": self._expert_accuracy(name),
            }

        # Confidence blends outcome clarity and expert agreement.
        confidence = self._compute_confidence(
            score, action, outcome, expert_contributions
        )

        verdict = {
            "subnet_id": subnet_id,
            "score": round(score, 4),
            "confidence": round(confidence, 4),
            "action": action,
            "note": note,
            "outcome_label": outcome_label,
            "expert_contributions": expert_contributions,
            "timestamp": self._now_iso(),
        }

        self._persist_verdict(verdict)
        self._update_track_records(decision, outcome, score)
        self._update_council_weights()
        self._append_learning_trail(verdict)
        if self.persist:
            self._save_state()
        return verdict

    def judge_outcome_only(
        self,
        subnet_id: int,
        decision: Dict[str, Any],
        outcome: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Convenience wrapper that always includes a subnet_id."""
        return self.judge_decision(decision, outcome, subnet_id=subnet_id)

    # ------------------------------------------------------------------
    # Learning internals
    # ------------------------------------------------------------------
    def _compute_confidence(
        self,
        score: float,
        action: str,
        outcome: Dict[str, Any],
        expert_contributions: Dict[str, Dict[str, Any]],
    ) -> float:
        """Confidence increases when the outcome is unambiguous and experts agree."""
        status = outcome.get("status", "unknown")
        is_overvalued = outcome.get("is_overvalued", False)
        emission = outcome.get("emission", 0.0) or 0.0
        social = outcome.get("social_mentions", 0) or 0

        # Outcome clarity: strong signals push confidence toward 1.0.
        clarity = 0.5
        if status in ("deprecated", "at-risk") or is_overvalued:
            clarity = 0.9
        elif status == "active" and emission >= 1.0 and social >= 100:
            clarity = 0.85
        elif status == "active":
            clarity = 0.7

        # Expert agreement: how aligned are the expert scores with the action.
        accuracies = [
            contrib.get("accuracy", 0.5) for contrib in expert_contributions.values()
        ]
        avg_accuracy = sum(accuracies) / len(accuracies) if accuracies else 0.5

        # Verdict extremity: scores near 0 or 1 are more confident than 0.5.
        extremity = 0.5 + abs(score - 0.5)

        confidence = (clarity * 0.4) + (avg_accuracy * 0.35) + (extremity * 0.25)
        return round(min(1.0, max(0.0, confidence)), 4)

    def _expert_accuracy(self, name: str) -> float:
        record = self._state.get("expert_track_records", {}).get(name, {})
        return record.get("accuracy", 0.5)

    def _persist_verdict(self, verdict: Dict[str, Any]) -> None:
        self._state.setdefault("verdicts", []).append(verdict)
        # Keep the persisted verdict list bounded to avoid unbounded growth.
        self._state["verdicts"] = self._state["verdicts"][-500:]

    def _update_track_records(
        self, decision: Dict[str, Any], outcome: Dict[str, Any], verdict_score: float
    ) -> None:
        """Update per-expert accuracy based on how their score predicted the outcome."""
        breakdown = decision.get("expert_breakdown", {})
        status = outcome.get("status", "unknown")
        is_overvalued = outcome.get("is_overvalued", False)
        emission = outcome.get("emission", 0.0) or 0.0
        social = outcome.get("social_mentions", 0) or 0

        # Derive an outcome score in [0, 1] from the observed metrics.
        if status in ("deprecated", "at-risk") or is_overvalued or emission < 0.5:
            outcome_score = 0.0
        elif status == "active" and emission >= 1.0 and social >= 100:
            outcome_score = 1.0
        else:
            outcome_score = 0.5

        records = self._state.setdefault("expert_track_records", {})
        for name in self.EXPERT_NAMES:
            expert = breakdown.get(name, {})
            predicted = expert.get("score", 0.5)
            error = abs(predicted - outcome_score)
            # Reward small error, penalize large error.
            sample = 1.0 - min(1.0, error * 2.0)

            record = records.setdefault(
                name,
                {
                    "correct": 0,
                    "total": 0,
                    "accuracy": 0.5,
                    "last_updated": self._now_iso(),
                },
            )
            record["correct"] = record.get("correct", 0) + sample
            record["total"] = record.get("total", 0) + 1
            total = record["total"]
            record["accuracy"] = round(record["correct"] / total, 4) if total else 0.5
            record["last_updated"] = self._now_iso()

    def _update_council_weights(self) -> None:
        """Rebalance council weights toward experts with higher recent accuracy."""
        records = self._state.get("expert_track_records", {})
        if not records:
            return

        accuracies = {
            name: records.get(name, {}).get("accuracy", 0.5)
            for name in self.EXPERT_NAMES
        }
        total = sum(accuracies.values())
        if total == 0:
            return

        # Softmax-ish normalization with a floor so no expert is fully silenced.
        new_weights = {}
        floor = 0.15
        remaining = 1.0 - floor * len(self.EXPERT_NAMES)
        for name in self.EXPERT_NAMES:
            share = accuracies[name] / total
            new_weights[name] = round(floor + remaining * share, 4)

        self._state["council_weights"] = new_weights

    def _append_learning_trail(self, verdict: Dict[str, Any]) -> None:
        """Keep a concise, human-readable learning trail for UI/API consumers."""
        trail_entry = {
            "timestamp": verdict["timestamp"],
            "subnet_id": verdict.get("subnet_id"),
            "action": verdict["action"],
            "outcome_label": verdict["outcome_label"],
            "score": verdict["score"],
            "confidence": verdict["confidence"],
            "note": verdict["note"],
        }
        trail = self._state.setdefault("learning_trail", [])
        trail.append(trail_entry)
        self._state["learning_trail"] = trail[-200:]

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
