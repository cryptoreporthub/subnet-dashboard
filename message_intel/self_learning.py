"""
Self-Learning Loop — feedback mechanism that improves over time.

After outcomes are recorded, this module:
- Compares predicted vs actual price movements
- Updates author_reliability scores
- Discovers pattern correlations
- Adjusts jury weights for future evaluations
"""

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.judge.adversarial import AdversarialJudge

logger = logging.getLogger(__name__)


class SelfLearning:
    """
    Feedback loop that refines message intelligence based on outcomes.

    Connects predictions to actual outcomes, scores authors, discovers
    pattern correlations, and adjusts the AdversarialJudge weights.
    """

    def __init__(
        self,
        db=None,
        judge: Optional[AdversarialJudge] = None,
    ):
        self.db = db
        self.judge = judge or AdversarialJudge()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def set_db(self, db) -> None:
        self.db = db

    # ── Author Reliability ────────────────────────────────────────────

    def update_author_reliability(self) -> None:
        """
        Score each author's prediction accuracy by comparing their
        message verdicts against actual price outcomes.
        """
        if self.db is None:
            return

        # Get all messages that have both verdicts and outcomes
        with self.db._connect() as conn:
            rows = conn.execute(
                """SELECT m.author_id, m.author_name, m.id as message_id,
                          v.verdict, v.predicted_direction,
                          po.outcome, po.pump_pct_max
                   FROM messages m
                   JOIN message_verdicts v ON v.message_id = m.id
                   JOIN price_outcomes po ON po.message_id = m.id
                   ORDER BY m.author_id"""
            ).fetchall()

        author_stats: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            row = dict(row)
            author_id = row.get("author_id") or "unknown"
            if author_id not in author_stats:
                author_stats[author_id] = {
                    "author_id": author_id,
                    "author_name": row.get("author_name", "Unknown"),
                    "total_messages": 0,
                    "correct_predictions": 0,
                }

            stats = author_stats[author_id]
            stats["total_messages"] += 1

            # Check if prediction was correct
            verdict = row.get("verdict", "neutral")
            direction = row.get("predicted_direction", "neutral")
            outcome = row.get("outcome", "stable")
            pump_pct = row.get("pump_pct_max") or 0.0

            if self._is_correct_prediction(verdict, direction, outcome, pump_pct):
                stats["correct_predictions"] += 1

        for author_id, stats in author_stats.items():
            total = stats["total_messages"]
            correct = stats["correct_predictions"]
            stats["accuracy_score"] = round(correct / total, 4) if total > 0 else 0.0
            self.db.upsert_author_reliability(stats)

        logger.info(
            "Updated reliability for %d authors", len(author_stats)
        )

    @staticmethod
    def _is_correct_prediction(
        verdict: str, direction: str, outcome: str, pump_pct: float
    ) -> bool:
        """
        Determine if a prediction was correct based on the outcome.

        - bullish/up predictions → pump or mild_pump = correct
        - bearish/down predictions → dump or mild_dump = correct
        - neutral predictions → stable = correct
        """
        if verdict in ("bullish",) or direction == "up":
            return outcome in ("pump", "mild_pump") or pump_pct > 2.0
        elif verdict in ("bearish",) or direction == "down":
            return outcome in ("dump", "mild_dump")
        else:
            return outcome == "stable"

    # ── Pattern Correlations ──────────────────────────────────────────

    def discover_patterns(self) -> List[Dict[str, Any]]:
        """
        Analyze past messages to discover patterns that correlate with
        successful predictions.

        Returns a list of pattern descriptions with match counts and
        success rates.
        """
        if self.db is None:
            return []

        with self.db._connect() as conn:
            rows = conn.execute(
                """SELECT m.id, m.content, a.hype_score, a.substance_score,
                          a.sentiment, v.verdict, v.predicted_direction,
                          po.outcome, po.pump_pct_max
                   FROM messages m
                   JOIN message_analysis a ON a.message_id = m.id
                   JOIN message_verdicts v ON v.message_id = m.id
                   JOIN price_outcomes po ON po.message_id = m.id"""
            ).fetchall()

        if not rows:
            return []

        patterns = [
            {
                "name": "high_substance_bullish",
                "description": "Bullish messages with high substance score (>0.6)",
                "matches": [],
            },
            {
                "name": "high_hype_pump",
                "description": "High hype score (>0.5) messages that predict pumps",
                "matches": [],
            },
            {
                "name": "specific_subnet_mention",
                "description": "Messages mentioning specific subnet numbers",
                "matches": [],
            },
            {
                "name": "tao_amount_target",
                "description": "Messages with specific TAO amount targets",
                "matches": [],
            },
            {
                "name": "low_substance_high_hype",
                "description": "Low substance (<0.3) with high hype (>0.6) — likely noise",
                "matches": [],
            },
        ]

        for row in rows:
            row = dict(row)
            content = row.get("content", "") or ""
            hype = row.get("hype_score") or 0.0
            substance = row.get("substance_score") or 0.0
            sentiment = row.get("sentiment", "neutral")
            verdict = row.get("verdict", "neutral")
            outcome = row.get("outcome", "stable")
            pump_pct = row.get("pump_pct_max") or 0.0

            is_success = self._is_correct_prediction(
                verdict, row.get("predicted_direction", "neutral"),
                outcome, pump_pct,
            )

            # Pattern 1: High substance + bullish
            if substance > 0.6 and sentiment == "bullish":
                patterns[0]["matches"].append(is_success)

            # Pattern 2: High hype
            if hype > 0.5:
                patterns[1]["matches"].append(is_success)

            # Pattern 3: Mentions subnet number
            if re.search(r"\b(subnet\s*#?\d+|sn\s*\d+)\b", content, re.IGNORECASE):
                patterns[2]["matches"].append(is_success)

            # Pattern 4: TAO amount target
            if re.search(r"\b\d+\.?\d*\s*TAO\b", content, re.IGNORECASE):
                patterns[3]["matches"].append(is_success)

            # Pattern 5: Low substance + high hype
            if substance < 0.3 and hype > 0.6:
                patterns[4]["matches"].append(is_success)

        # Compute stats for each pattern
        results = []
        for p in patterns:
            total = len(p["matches"])
            successes = sum(1 for m in p["matches"] if m)
            success_rate = round(successes / total, 4) if total > 0 else 0.0
            confidence = round(
                (success_rate - 0.5) * min(1.0, total / 10.0), 4
            ) if total > 0 else 0.0

            pattern_entry = {
                "pattern_description": p["description"],
                "match_count": total,
                "success_rate": success_rate,
                "confidence": max(0.0, min(1.0, confidence)),
            }
            self.db.save_pattern(pattern_entry)
            results.append(pattern_entry)

        logger.info("Discovered %d pattern correlations", len(results))
        return results

    # ── Jury Weight Adjustment ────────────────────────────────────────

    def adjust_jury_weights(self) -> None:
        """
        Adjust the AdversarialJudge council weights based on observed
        pattern performance.

        Patterns with high success rates boost the influence of their
        corresponding expert dimensions.
        """
        if self.db is None:
            return

        patterns = self.db.list_patterns(limit=20)
        if not patterns:
            return

        weights = self.judge.get_council_weights()

        # Map pattern performance to weight adjustments
        for p in patterns:
            success = p.get("success_rate", 0.5)
            desc = p.get("pattern_description", "")

            if "substance" in desc.lower() or "specific subnet" in desc.lower():
                weights["quant"] = min(0.5, weights.get("quant", 0.3) + (success - 0.5) * 0.1)
            if "hype" in desc.lower():
                weights["hype"] = min(0.4, weights.get("hype", 0.25) + (success - 0.5) * 0.08)
            if "noise" in desc.lower() and success < 0.5:
                weights["contrarian"] = min(0.4, weights.get("contrarian", 0.2) + 0.05)

        # Normalize weights to sum to 1.0
        total = sum(weights.values())
        if total > 0:
            for k in weights:
                weights[k] = round(weights[k] / total, 4)

        logger.info("Adjusted jury weights: %s", weights)

    # ── Background Runner ─────────────────────────────────────────────

    def start_background_learning(self, interval: int = 600) -> None:
        """
        Start a background thread that periodically runs the learning loop.

        Args:
            interval: Seconds between learning cycles (default 600 = 10 min).
        """
        if self._running:
            return
        self._running = True

        def _loop():
            while self._running:
                try:
                    self.update_author_reliability()
                    self.discover_patterns()
                    self.adjust_jury_weights()
                    logger.info("Self-learning cycle completed")
                except Exception as e:
                    logger.error("Self-learning error: %s", e)
                time.sleep(interval)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()
        logger.info(
            "Self-learning background loop started (interval=%ds)", interval
        )

    def stop(self) -> None:
        self._running = False