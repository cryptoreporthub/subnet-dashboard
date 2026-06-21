"""
LearningLoop — self-learning loop that compares verdicts against outcomes.

Phase 0: The loop now resolves hypotheses against actual price data
from the Price Oracle, records outcomes, and updates expert weights
based on price-anchored accuracy.
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.judge.adversarial import AdversarialJudge
from internal.council.mindmap_bridge import MindmapBridge
from internal.price_oracle import fetch_prices


OUTCOMES_PATH = os.environ.get("OUTCOMES_PATH", "data/outcomes.jsonl")
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")


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


class LearningLoop:
    """
    Self-learning loop that resolves hypotheses against price data,
    records outcomes, and updates expert weights.
    """

    def __init__(
        self,
        soul_map_path: str = SOUL_MAP_PATH,
        outcomes_path: str = OUTCOMES_PATH,
    ):
        self.soul_map_path = soul_map_path
        self.outcomes_path = outcomes_path
        self.soul_map = _load_json(soul_map_path)
        self.outcomes = self._load_outcomes()
        self.bridge = MindmapBridge(persistence_path=soul_map_path)
        self.judge = AdversarialJudge(persistence_path=soul_map_path)

    def _load_outcomes(self) -> List[Dict[str, Any]]:
        outcomes = []
        if os.path.exists(self.outcomes_path):
            with open(self.outcomes_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            outcomes.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        return outcomes

    def _append_outcome(self, outcome: Dict[str, Any]) -> None:
        dir_name = os.path.dirname(self.outcomes_path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        with open(self.outcomes_path, "a") as f:
            f.write(json.dumps(outcome) + "\n")
        self.outcomes.append(outcome)

    def run(self) -> Dict[str, Any]:
        """
        Execute one cycle of the learning loop.

        1. Fetch current prices for tracked tokens.
        2. Resolve pending hypotheses against current prices.
        3. Update expert weights based on outcomes.
        4. Record outcomes.
        """
        run_at = _now_iso()
        summary = {
            "run_at": run_at,
            "hypotheses_resolved": 0,
            "outcomes_recorded": 0,
            "price_fetch_ok": False,
            "error": None,
        }

        try:
            # Fetch current prices.
            prices_result = fetch_prices()
            summary["price_fetch_ok"] = not prices_result.get("errors")
            summary["prices"] = {
                token: info.get("price_usd")
                for token, info in prices_result.get("prices", {}).items()
            }

            # Resolve pending hypotheses.
            pending = self.bridge.get_pending_hypotheses()
            for h in pending:
                # Try to find a price for this subnet.
                # For now, use TAO as a proxy for subnet tokens.
                tao_price = (
                    prices_result.get("prices", {}).get("TAO", {}).get("price_usd")
                )
                if tao_price:
                    resolved = self.bridge.resolve_hypothesis(
                        h["subnet_id"], tao_price
                    )
                    if resolved:
                        summary["hypotheses_resolved"] += 1

                        # Record outcome.
                        outcome = {
                            "type": "hypothesis_resolution",
                            "subnet_id": h["subnet_id"],
                            "predicted_delta_pct": h["predicted_delta_pct"],
                            "actual_delta_pct": resolved.get("actual_delta_pct", 0),
                            "outcome_score": resolved.get("outcome_score", 0),
                            "resolved_at": _now_iso(),
                        }
                        self._append_outcome(outcome)
                        summary["outcomes_recorded"] += 1

                        # Update expert weights based on outcome.
                        was_correct = (resolved.get("outcome_score", 0) or 0) >= 0.7
                        for expert in ["quant", "hype", "contrarian", "technical"]:
                            self.judge.update_expert_accuracy(expert, was_correct)

            # Update last run timestamp.
            self.soul_map["last_run"] = run_at
            self._persist_soul_map()

        except Exception as e:
            summary["error"] = str(e)

        return summary

    def _persist_soul_map(self) -> None:
        dir_name = os.path.dirname(self.soul_map_path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        temp = self.soul_map_path + ".tmp"
        with open(temp, "w") as f:
            json.dump(self.soul_map, f, indent=2)
        os.replace(temp, self.soul_map_path)

    def _compute_aligned_pct(self) -> float:
        if not self.outcomes:
            return 0.0
        aligned = sum(
            1 for o in self.outcomes
            if (o.get("outcome_score", 0) or 0) >= 0.7
        )
        return round(aligned / len(self.outcomes) * 100, 2)

    def _compute_divergent_pct(self) -> float:
        if not self.outcomes:
            return 0.0
        divergent = sum(
            1 for o in self.outcomes
            if (o.get("outcome_score", 0) or 0) < 0.3
        )
        return round(divergent / len(self.outcomes) * 100, 2)