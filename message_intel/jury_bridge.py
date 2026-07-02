"""
Jury Bridge — connects message analysis to the existing AdversarialJudge.

Takes NLP analysis output, wraps it into a signal format the jury can
evaluate, calls the existing AdversarialJudge scoring, and returns a
verdict with conviction and reasoning. Also updates the Mind Map.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    from internal.council.judge.adversarial import AdversarialJudge
    from internal.council.mindmap_bridge import MindmapBridge
except ModuleNotFoundError as _e:  # pragma: no cover - internal modules absent in main
    logger = logging.getLogger(__name__)
    logger.warning(
        "Internal council modules not available (%s). Using fallback judge/mindmap.",
        _e,
    )

    class AdversarialJudge:
        """Minimal fallback judge that returns a neutral verdict."""

        def __init__(self, *args, **kwargs):
            self.weights = {"quant": 0.3, "hype": 0.25, "contrarian": 0.2, "technical": 0.25}

        def judge_decision(self, signal: Dict[str, Any], outcome: Dict[str, Any]) -> Dict[str, Any]:
            consensus = float(signal.get("consensus_score", 0.5))
            action = signal.get("recommended_action", "hold")
            if action == "accumulate":
                label = "validated"
            elif action == "reduce":
                label = "contradicted"
            else:
                label = "neutral"
            return {
                "outcome_label": label,
                "confidence": round(consensus, 4),
                "note": "Fallback adversarial verdict (internal council unavailable).",
            }

    class MindmapBridge:
        """Minimal fallback mindmap bridge that keeps state in memory."""

        def __init__(self, *args, **kwargs):
            self.soul_map_state: Dict[str, Any] = {}

        def _save_to_disk(self) -> None:
            pass

        def log_simivision_feedback(
            self, subnet_id: int, outcome: int, note: str = ""
        ) -> None:
            pass

logger = logging.getLogger(__name__)


class JuryBridge:
    """
    Bridge that transforms message analysis into signals the
    AdversarialJudge can evaluate and records results in the Mind Map.
    """

    def __init__(
        self,
        judge: Optional[AdversarialJudge] = None,
        mindmap: Optional[MindmapBridge] = None,
    ):
        self.judge = judge or AdversarialJudge()
        self.mindmap = mindmap or MindmapBridge()

    def evaluate(
        self, message_id: int, content: str, analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Evaluate a message through the adversarial jury.

        Args:
            message_id: Database ID of the message.
            content: Raw message text.
            analysis: NLP analysis output dict.

        Returns:
            Verdict dict with keys: verdict, conviction, reasoning,
            predicted_direction, predicted_magnitude, predicted_timeframe,
            predicted_confidence.
        """
        # Build a decision signal from the NLP analysis
        signal = self._build_signal(message_id, content, analysis)

        # Call the AdversarialJudge — it returns a verdict dict
        # We use a synthetic outcome based on analysis strength
        outcome = self._build_outcome(analysis)
        verdict = self.judge.judge_decision(signal, outcome)

        # Map the judge's output to our prediction fields
        result = self._map_verdict(verdict, analysis)

        # Update the Mind Map with message-derived knowledge
        self._update_mindmap(content, analysis, result)

        logger.info(
            "Jury verdict for message %d: %s (conviction=%.2f)",
            message_id,
            result["verdict"],
            result["conviction"],
        )
        return result

    def _build_signal(
        self, message_id: int, content: str, analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Wrap NLP analysis into a selector-style decision dict that the
        AdversarialJudge.judge_decision() can process.
        """
        sentiment = analysis.get("sentiment", "neutral")
        hype = analysis.get("hype_score", 0.0)
        substance = analysis.get("substance_score", 0.0)
        influence = analysis.get("influence_score", 0.0)

        # Determine recommended action from sentiment + influence
        if sentiment == "bullish" and influence >= 0.5:
            action = "accumulate"
        elif sentiment == "bearish" and influence >= 0.5:
            action = "reduce"
        else:
            action = "hold"

        # Build a consensus score from the analysis dimensions
        consensus_score = round(
            (substance * 0.35 + (influence * 0.25) + (1.0 - hype * 0.3) * 0.2 + 0.2),
            4,
        )
        consensus_score = min(1.0, max(0.0, consensus_score))

        # Map sentiment to a numeric score for the experts
        sentiment_map = {"bullish": 0.8, "bearish": 0.2, "neutral": 0.5}
        sentiment_score = sentiment_map.get(sentiment, 0.5)

        return {
            "subnet_id": None,
            "consensus_score": consensus_score,
            "recommended_action": action,
            "expert_breakdown": {
                "quant": {
                    "score": substance,
                    "metrics": {"substance_index": substance * 100},
                },
                "hype": {
                    "score": hype,
                    "sentiment": sentiment,
                    "metrics": {"hype_index": hype * 100},
                },
                "contrarian": {
                    "score": 1.0 - sentiment_score,
                    "signal": "sell" if sentiment == "bullish" else "buy",
                    "metrics": {"contrarian_index": (1.0 - sentiment_score) * 100},
                },
                "technical": {
                    "score": influence,
                    "signal": action,
                    "metrics": {"influence_index": influence * 100},
                },
            },
        }

    @staticmethod
    def _build_outcome(analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a synthetic outcome dict from analysis strength so the
        AdversarialJudge has something to evaluate.
        """
        hype = analysis.get("hype_score", 0.0)
        substance = analysis.get("substance_score", 0.0)
        influence = analysis.get("influence_score", 0.0)

        return {
            "status": "active",
            "emission": max(0.1, substance * 2.0),
            "social_mentions": int(influence * 2000),
            "is_overvalued": hype > 0.7 and substance < 0.3,
        }

    @staticmethod
    def _map_verdict(
        jury_verdict: Dict[str, Any], analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Map the AdversarialJudge's verdict into our message verdict format
        with prediction fields.
        """
        sentiment = analysis.get("sentiment", "neutral")
        influence = analysis.get("influence_score", 0.0)

        # Determine predicted direction from sentiment
        if sentiment == "bullish" and influence >= 0.4:
            predicted_direction = "up"
            predicted_magnitude = round(influence * 0.15, 4)
        elif sentiment == "bearish" and influence >= 0.4:
            predicted_direction = "down"
            predicted_magnitude = round(influence * 0.1, 4)
        else:
            predicted_direction = "neutral"
            predicted_magnitude = 0.0

        # Timeframe: high substance + high influence = shorter
        substance = analysis.get("substance_score", 0.0)
        if substance > 0.6 and influence > 0.6:
            predicted_timeframe = "1h-4h"
        elif substance > 0.4:
            predicted_timeframe = "4h-24h"
        else:
            predicted_timeframe = "24h-7d"

        base_confidence = jury_verdict.get("confidence", 0.5)
        predicted_confidence = round(
            (base_confidence + influence) / 2.0, 4
        )

        # Map outcome_label to a simple verdict string
        label = jury_verdict.get("outcome_label", "neutral")
        verdict_str = {
            "validated": "bullish",
            "contradicted": "bearish",
            "neutral": "neutral",
        }.get(label, "neutral")

        return {
            "verdict": verdict_str,
            "conviction": round(base_confidence * 100, 2),
            "reasoning": jury_verdict.get(
                "note", "Evaluated by adversarial jury."
            ),
            "predicted_direction": predicted_direction,
            "predicted_magnitude": predicted_magnitude,
            "predicted_timeframe": predicted_timeframe,
            "predicted_confidence": predicted_confidence,
        }

    def _update_mindmap(
        self, content: str, analysis: Dict[str, Any], verdict: Dict[str, Any]
    ) -> None:
        """
        Feed message intelligence into the Mind Map as a knowledge node.

        This creates a traceable node in the Soul-Map so the self-learning
        loop can reference it later.
        """
        try:
            entities = analysis.get("entities", {})
            subnets = entities.get("subnets", [])

            mindmap_entry = {
                "type": "telegram_intel",
                "content_preview": content[:200],
                "sentiment": analysis.get("sentiment"),
                "hype_score": analysis.get("hype_score"),
                "substance_score": analysis.get("substance_score"),
                "verdict": verdict.get("verdict"),
                "conviction": verdict.get("conviction"),
                "predicted_direction": verdict.get("predicted_direction"),
                "entities": entities,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # Store in the mindmap bridge's soul_map_state
            if not hasattr(self.mindmap, "soul_map_state"):
                return
            intel_log = self.mindmap.soul_map_state.setdefault(
                "telegram_intel_log", []
            )
            intel_log.append(mindmap_entry)
            # Keep only recent entries
            self.mindmap.soul_map_state["telegram_intel_log"] = intel_log[-200:]
            self.mindmap._save_to_disk()

            # Log as SimiVision feedback if subnet entities found
            for subnet_str in subnets:
                numbers = re.findall(r"\d+", subnet_str)
                for num_str in numbers:
                    try:
                        subnet_id = int(num_str)
                        boost = 0.02 if verdict.get("verdict") == "bullish" else -0.02
                        self.mindmap.log_simivision_feedback(
                            subnet_id=subnet_id,
                            outcome=1 if boost > 0 else -1,
                            note=f"Telegram intel: {verdict.get('verdict')} ({verdict.get('conviction', 0)}%)",
                        )
                    except (ValueError, TypeError):
                        continue

        except Exception as e:
            logger.warning("Failed to update mindmap: %s", e)


