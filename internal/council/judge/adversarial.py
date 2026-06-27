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
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class AdversarialJudge:
    """
    Compares predictions against actual outcomes and updates the Soul-Map
    with verdicts, expert track records, and adaptive council weights.
    """

    DEFAULT_WEIGHTS = {"quant": 0.3, "hype": 0.25, "contrarian": 0.2, "technical": 0.25}
    EXPERT_NAMES = ("quant", "hype", "contrarian", "technical")

    def __init__(
        self,
        persistence_path: str = "data/soul_map.json",
        registry_path: str = "config/registry.json",
        auto_persist: bool = False,
    ):
        self.persistence_path = persistence_path
        self.registry_path = registry_path
        self.auto_persist = auto_persist
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
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        data: Dict[str, Any] = {}
        if os.path.exists(self.persistence_path):
            try:
                with open(self.persistence_path, "r") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        data["adversarial_state"] = self._state
        fd, temp_path = tempfile.mkstemp(dir=dir_name or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(temp_path, self.persistence_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def persist(self) -> None:
        """Public persistence hook used by the learning-loop scheduler."""
        self._save_state()

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
            "indicator_context": decision.get("indicator_context"),
            "timestamp": self._now_iso(),
        }

        self._persist_verdict(verdict)
        self._update_track_records(decision, outcome, score)
        self._update_council_weights()
        self._append_learning_trail(verdict)
        if self.auto_persist:
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


    # ==================================================================
    # PREDICTION-LEVEL JUDGING (learning loop closure)
    # ==================================================================
    # These methods judge stored predictions against their resolutions and
    # drive per-expert accuracy, calibration buckets, signal attribution,
    # streaks and council-weight updates. They complement the existing
    # judge_decision(decision, outcome, subnet_id) path used by the
    # orchestrator; both write into the same adversarial_state.

    CALIBRATION_BUCKETS = [(50, 60), (60, 70), (70, 80), (80, 90), (90, 101)]

    def judge_prediction(self, prediction: Dict[str, Any], resolution: Dict[str, Any]) -> Dict[str, Any]:
        """Judge a resolved prediction: which experts were right/wrong, failure tags, learning note."""
        outcome = (resolution or {}).get("outcome") or prediction.get("outcome")
        experts = list(prediction.get("experts_involved", []) or [])
        signal_tags = list(prediction.get("signal_tags", []) or [])
        predicted_pct = float(prediction.get("predicted_pct", 0) or 0)
        actual_pct = (resolution or {}).get("actual_pct")
        if actual_pct is None:
            actual_pct = prediction.get("actual_pct")
        actual_pct = float(actual_pct) if actual_pct is not None else None

        correct = outcome == "correct"
        partial = outcome == "partial"
        wrong = outcome == "wrong"

        # Per-expert credit/blame.
        expert_results = {}
        for name in experts:
            expert_results[name] = "correct" if correct else ("partial" if partial else "wrong")
            self.update_expert_accuracy(name, correct=correct, partial=partial)

        # Failure tags for wrong/partial outcomes.
        failure_tags = self._failure_tags(prediction, resolution, outcome)

        # Magnitude error (signed).
        magnitude_error = None
        if actual_pct is not None:
            magnitude_error = round(actual_pct - predicted_pct, 2)

        note = self._learning_note(outcome, failure_tags, magnitude_error)

        verdict = {
            "timestamp": self._now_iso(),
            "prediction_id": prediction.get("id"),
            "subnet": prediction.get("subnet") or prediction.get("name"),
            "netuid": prediction.get("netuid"),
            "outcome": outcome,
            "experts_involved": experts,
            "expert_results": expert_results,
            "signal_tags": signal_tags,
            "failure_tags": failure_tags,
            "magnitude_error": magnitude_error,
            "predicted_pct": predicted_pct,
            "actual_pct": actual_pct,
            "conviction": prediction.get("conviction"),
            "note": note,
        }
        self._record_prediction_verdict(verdict)
        return verdict

    def _failure_tags(self, prediction: Dict[str, Any], resolution: Dict[str, Any], outcome: str) -> List[str]:
        """Generate failure tags explaining why a prediction missed."""
        if outcome in ("correct", "expired"):
            return []
        tags = []
        signal_tags = set(prediction.get("signal_tags", []) or [])
        conviction = int(prediction.get("conviction", 50) or 50)
        reasons = " ".join(str(r) for r in (prediction.get("reasons", []) or [])).lower()

        if conviction >= 80 and outcome != "correct":
            tags.append("conviction_overconfidence")
        if "rsi_overbought" in signal_tags or "overbought" in reasons:
            tags.append("overbought_false_positive")
        if "macd_crossover" in signal_tags or "macd" in reasons:
            tags.append("macd_false_signal")
        if "high_emission" in signal_tags or "emission" in reasons:
            tags.append("emission_trap")
        if not tags:
            tags.append("signal_misread")
        return tags

    def _learning_note(self, outcome: str, failure_tags: List[str], magnitude_error) -> str:
        if outcome == "correct":
            return "Prediction confirmed — reinforce contributing signals."
        if outcome == "partial":
            return f"Direction right, magnitude short (err {magnitude_error}). Dampen conviction on {', '.join(failure_tags) or 'weak signals'}."
        if outcome == "wrong":
            return f"Direction wrong (err {magnitude_error}). Penalize {', '.join(failure_tags) or 'misread signals'}."
        return "Prediction expired without resolution."

    def update_expert_accuracy(self, expert_name: str, correct: bool, partial: bool = False) -> Dict[str, Any]:
        """Track total / correct / accuracy / streaks for a single expert."""
        records = self._state.setdefault("expert_track_records", {})
        rec = records.setdefault(expert_name, {
            "total": 0, "correct_count": 0, "partial_count": 0,
            "accuracy_pct": 0.0, "current_streak": 0, "best_streak": 0,
        })
        rec["total"] = int(rec.get("total", 0)) + 1
        if correct:
            rec["correct_count"] = int(rec.get("correct_count", 0)) + 1
            rec["current_streak"] = int(rec.get("current_streak", 0)) + 1
        elif partial:
            rec["partial_count"] = int(rec.get("partial_count", 0)) + 1
            # Partial breaks a winning streak but does not flip to losing.
            rec["current_streak"] = 0
        else:
            rec["current_streak"] = 0
        if rec["current_streak"] > int(rec.get("best_streak", 0)):
            rec["best_streak"] = rec["current_streak"]
        judged = rec["correct_count"] + rec["partial_count"]
        rec["accuracy_pct"] = round(rec["correct_count"] / judged, 4) if judged else 0.0
        return rec

    def update_council_weights(self, verdict: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
        """Adjust council weights from a prediction verdict and persist.

        +0.02 correct, -0.03 wrong, +0.005 partial, normalized to 1.0,
        dampened by min(1.0, resolved/10), with recency boost (last 30
        verdicts count 2x).
        """
        weights = dict(self._state.get("council_weights") or {})
        for name in ("quant", "hype", "contrarian", "technical"):
            weights.setdefault(name, 1.0)

        trail = self._state.get("learning_trail", []) or []
        resolved = len(trail)
        dampen = min(1.0, resolved / 10.0) if resolved else 0.0

        if verdict:
            delta_map = {"correct": 0.02, "partial": 0.005, "wrong": -0.03}
            delta = delta_map.get(verdict.get("outcome"), 0.0) * dampen
            for name in (verdict.get("experts_involved") or []):
                if name in weights:
                    weights[name] = round(float(weights[name]) + delta, 4)

        # Recency weighting: last 30 verdicts count double.
        recent = trail[-30:]
        for v in recent:
            outcome = v.get("outcome_label") or v.get("outcome")
            delta_map = {"correct": 0.02, "partial": 0.005, "wrong": -0.03}
            delta = delta_map.get(outcome, 0.0) * dampen * 0.5  # half-weight for recency pass
            for name in (v.get("experts_involved") or []):
                if name in weights:
                    weights[name] = round(float(weights[name]) + delta, 4)

        # Normalize to a mean of 1.0 so weights stay comparable over time.
        vals = [max(0.05, float(w)) for w in weights.values()]
        mean = sum(vals) / len(vals) if vals else 1.0
        weights = {k: round(max(0.05, float(v) / mean), 4) for k, v in weights.items()}

        self._state["council_weights"] = weights
        self._state["last_weight_update"] = self._now_iso()
        return weights

    def get_calibration_buckets(self) -> List[Dict[str, Any]]:
        """Accuracy per conviction bucket (50-60, 60-70, 70-80, 80-90, 90-100)."""
        verdicts = self._state.get("prediction_verdicts", []) or []
        buckets = []
        for lo, hi in self.CALIBRATION_BUCKETS:
            in_bucket = [
                v for v in verdicts
                if lo <= int(v.get("conviction") or 0) < hi
            ]
            judged = [v for v in in_bucket if v.get("outcome") in ("correct", "partial", "wrong")]
            correct = sum(1 for v in judged if v.get("outcome") == "correct")
            acc = round(correct / len(judged), 4) if judged else None
            buckets.append({
                "bucket": f"{lo}-{hi if hi <= 100 else 100}",
                "total": len(judged),
                "correct": correct,
                "accuracy": acc,
            })
        return buckets

    def get_signal_attribution(self) -> List[Dict[str, Any]]:
        """Accuracy per signal_tag across all judged predictions."""
        verdicts = self._state.get("prediction_verdicts", []) or []
        agg: Dict[str, Dict[str, int]] = {}
        for v in verdicts:
            outcome = v.get("outcome")
            if outcome not in ("correct", "partial", "wrong"):
                continue
            for tag in (v.get("signal_tags") or []):
                slot = agg.setdefault(tag, {"total": 0, "correct": 0, "partial": 0, "wrong": 0})
                slot["total"] += 1
                if outcome in slot:
                    slot[outcome] += 1
        rows = []
        for tag, s in agg.items():
            rows.append({
                "signal": tag,
                "total": s["total"],
                "correct": s["correct"],
                "partial": s["partial"],
                "wrong": s["wrong"],
                "accuracy": round(s["correct"] / s["total"], 4) if s["total"] else None,
            })
        rows.sort(key=lambda r: r["total"], reverse=True)
        return rows

    def get_streaks(self) -> List[Dict[str, Any]]:
        """Expert leaderboard by accuracy and best streak."""
        records = self._state.get("expert_track_records", {}) or {}
        rows = []
        for name, rec in records.items():
            judged = rec.get("correct_count", 0) + rec.get("partial_count", 0)
            rows.append({
                "expert": name,
                "total": rec.get("total", 0),
                "correct": rec.get("correct_count", 0),
                "partial": rec.get("partial_count", 0),
                "accuracy": rec.get("accuracy_pct", 0.0),
                "current_streak": rec.get("current_streak", 0),
                "best_streak": rec.get("best_streak", 0),
            })
        rows.sort(key=lambda r: r["accuracy"], reverse=True)
        return rows

    def _record_prediction_verdict(self, verdict: Dict[str, Any]) -> None:
        pv = self._state.setdefault("prediction_verdicts", [])
        pv.append(verdict)
        self._state["prediction_verdicts"] = pv[-500:]
        # Mirror into learning_trail so update_council_weights recency pass sees it.
        trail_entry = {
            "timestamp": verdict["timestamp"],
            "subnet_id": verdict.get("netuid"),
            "action": "predict",
            "outcome_label": verdict.get("outcome"),
            "score": verdict.get("conviction"),
            "confidence": verdict.get("conviction"),
            "note": verdict.get("note"),
            "experts_involved": verdict.get("experts_involved"),
        }
        trail = self._state.setdefault("learning_trail", [])
        trail.append(trail_entry)
        self._state["learning_trail"] = trail[-200:]


    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
