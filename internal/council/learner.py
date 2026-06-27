"""
Learning Loop — closes the prediction -> resolve -> judge -> weights cycle.

Two layers coexist here:

1. ``LearningLoop`` (legacy) — the orchestrator-driven outcome comparison used
   by the older council path. Kept intact so existing tests and the
   ``/api/learning-loop/*`` endpoints continue to work.

2. ``LearningLoopScheduler`` (new) — the prediction-based closed loop:
       resolve_due_predictions() -> judge.judge_prediction() ->
       judge.update_council_weights() -> judge.persist() ->
       (caller generates new predictions) -> status()

The scheduler runs every 30 minutes from server.py and is the canonical
implementation of the self-learning loop described in the spec.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ======================================================================
# Legacy LearningLoop (orchestrator-driven) — preserved for compatibility
# ======================================================================


class LearningLoop:
    def __init__(self, soul_map_path="data/soul_map.json", outcomes_path="data/outcomes.jsonl"):
        self.soul_map_path = soul_map_path
        self.outcomes_path = outcomes_path
        self._ensure_files()
        self.soul_map = self._load_json(soul_map_path)
        self.outcomes = self._load_jsonl(outcomes_path)

    def _ensure_files(self):
        os.makedirs(os.path.dirname(self.soul_map_path) or ".", exist_ok=True)
        if not os.path.exists(self.soul_map_path):
            with open(self.soul_map_path, "w") as f:
                json.dump({"verdicts": [], "expert_weights": {}}, f)
        if not os.path.exists(self.outcomes_path):
            open(self.outcomes_path, "w").close()

    def _load_json(self, path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _load_jsonl(self, path):
        outcomes = []
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            outcomes.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        return outcomes

    def run(self):
        from internal.council.orchestrator import Orchestrator
        from internal.council.adversarial_judge import judge_decision

        orch = Orchestrator()
        result = orch.run_daily_rotation()
        decisions = result.get("daily_output", {}).get("decisions", [])

        for d in decisions:
            verdict = judge_decision(d)
            entry = {
                "netuid": d.get("netuid"),
                "timestamp": datetime.utcnow().isoformat(),
                "decision": d.get("action", "hold"),
                "consensus_score": d.get("consensus_score", 0),
                "brain_recommendation": d.get("brain_recommendation", ""),
                "verdict": verdict.get("verdict", "neutral"),
                "verdict_confidence": verdict.get("confidence", 0.5),
            }
            self._append_outcome(entry)

        if len(self.outcomes) >= 2:
            self._compare_outcomes()

        self.soul_map["last_run"] = datetime.utcnow().isoformat()
        self._save_soul_map()

        return {
            "last_run": self.soul_map.get("last_run"),
            "total_verdicts": len(self.soul_map.get("verdicts", [])),
            "total_outcomes": len(self.outcomes),
            "expert_weights": self.soul_map.get("expert_weights", {}),
            "aligned_pct": self._compute_aligned_pct(),
            "divergent_pct": self._compute_divergent_pct(),
        }

    def _append_outcome(self, entry):
        with open(self.outcomes_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        self.outcomes.append(entry)

    def _compare_outcomes(self):
        weights = self.soul_map.get("expert_weights")
        if not weights:
            weights = {
                "QuantExpert": 1.0, "HypeExpert": 1.0,
                "ContrarianExpert": 1.0, "TechnicalExpert": 1.0,
            }
        recent = self.outcomes[-5:] if len(self.outcomes) >= 5 else self.outcomes
        aligned = sum(1 for o in recent if o.get("verdict") == "aligned")
        divergent = sum(1 for o in recent if o.get("verdict") == "divergent")
        if divergent > aligned:
            for k in weights:
                weights[k] = max(0.5, weights[k] - 0.05)
        elif aligned > divergent:
            for k in weights:
                weights[k] = min(2.0, weights[k] + 0.02)
        self.soul_map["expert_weights"] = weights
        self._save_soul_map()

    def _save_soul_map(self):
        with open(self.soul_map_path, "w") as f:
            json.dump(self.soul_map, f, indent=2)

    def _compute_aligned_pct(self):
        if not self.outcomes:
            return 0.0
        aligned = sum(1 for o in self.outcomes if o.get("verdict") == "aligned")
        return round(aligned / len(self.outcomes) * 100, 1)

    def _compute_divergent_pct(self):
        if not self.outcomes:
            return 0.0
        divergent = sum(1 for o in self.outcomes if o.get("verdict") == "divergent")
        return round(divergent / len(self.outcomes) * 100, 1)


# ======================================================================
# LearningLoopScheduler — the real prediction-based closed loop
# ======================================================================


class LearningLoopScheduler:
    """Runs the closed learning loop on a schedule.

    Steps per run:
      1. outcome_resolver.resolve_due_predictions()
      2. judge.judge_prediction() for each resolved prediction
      3. judge.update_council_weights() (per verdict + recency)
      4. judge.persist()  -> soul_map.json
      5. (new predictions are generated by the caller / server)
      6. status() returns real stats
    """

    def __init__(
        self,
        store=None,
        resolver=None,
        judge=None,
        soul_map_path: str = "data/soul_map.json",
    ):
        from data.prediction_store import PredictionStore
        from data.outcome_resolver import OutcomeResolver
        from internal.council.judge.adversarial import AdversarialJudge

        self.soul_map_path = soul_map_path
        self.store = store or PredictionStore()
        self.resolver = resolver or OutcomeResolver(store=self.store)
        self.judge = judge or AdversarialJudge(persistence_path=soul_map_path)
        self._lock = threading.RLock()
        self.last_run: Optional[str] = None
        self.last_summary: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    def run(self, market_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute one full learning-loop pass."""
        with self._lock:
            resolved = self.resolver.resolve_due_predictions()
            verdicts: List[Dict[str, Any]] = []
            for entry in resolved:
                try:
                    prediction = dict(entry)
                    resolution = entry.get("resolution") or {}
                    verdict = self.judge.judge_prediction(prediction, resolution)
                    self.judge.update_council_weights(verdict)
                    verdicts.append(verdict)
                except Exception as exc:
                    logger.warning("judge failed for %s: %s", entry.get("id"), exc)

            # Persist weights + track records + verdicts to soul_map.json.
            try:
                self.judge.persist()
            except Exception as exc:
                logger.warning("judge persist failed: %s", exc)

            # Regime detection (does not mutate persisted weights; surfaced in status).
            from internal.council.weights import detect_regime, load_weights
            regime = detect_regime(market_data)

            self.last_run = _now_iso()
            summary = self._summary(verdicts, regime, load_weights(self.soul_map_path))
            self.last_summary = summary
            return summary

    # ------------------------------------------------------------------
    def _summary(self, verdicts: List[Dict[str, Any]], regime: str, weights: Dict[str, float]) -> Dict[str, Any]:
        stats = self.store.get_stats()
        return {
            "last_run": self.last_run,
            "resolved_this_run": len(verdicts),
            "total": stats.get("total", 0),
            "pending": stats.get("pending", 0),
            "resolved": stats.get("resolved", 0),
            "correct": stats.get("correct", 0),
            "partial": stats.get("partial", 0),
            "wrong": stats.get("wrong", 0),
            "expired": stats.get("expired", 0),
            "accuracy_pct": round(stats.get("accuracy", 0.0) * 100, 1),
            "expert_weights": weights,
            "expert_accuracy": self.judge.get_streaks(),
            "calibration": self.judge.get_calibration_buckets(),
            "signal_attribution": self.judge.get_signal_attribution(),
            "regime": regime,
            "verdicts": verdicts,
        }

    # ------------------------------------------------------------------
    def status(self, market_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Return real learning-loop stats without running the loop."""
        from internal.council.weights import detect_regime, load_weights
        stats = self.store.get_stats()
        return {
            "last_run": self.last_run,
            "total": stats.get("total", 0),
            "pending": stats.get("pending", 0),
            "resolved": stats.get("resolved", 0),
            "correct": stats.get("correct", 0),
            "partial": stats.get("partial", 0),
            "wrong": stats.get("wrong", 0),
            "expired": stats.get("expired", 0),
            "accuracy_pct": round(stats.get("accuracy", 0.0) * 100, 1),
            "expert_weights": load_weights(self.soul_map_path),
            "expert_accuracy": self.judge.get_streaks(),
            "calibration": self.judge.get_calibration_buckets(),
            "signal_attribution": self.judge.get_signal_attribution(),
            "regime": detect_regime(market_data),
        }


# Module-level singleton used by server.py.
SCHEDULER: Optional[LearningLoopScheduler] = None


def get_scheduler() -> LearningLoopScheduler:
    global SCHEDULER
    if SCHEDULER is None:
        SCHEDULER = LearningLoopScheduler()
    return SCHEDULER


def run_learning_loop(market_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_scheduler().run(market_data=market_data)


def learning_status(market_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_scheduler().status(market_data=market_data)
