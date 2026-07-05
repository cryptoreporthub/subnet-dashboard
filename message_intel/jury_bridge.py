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
except ModuleNotFoundError as _e:
    logger = logging.getLogger(__name__)
    logger.warning(
        "Internal council modules not available (%s). Using fallback judge/mindmap.",
        _e,
    )

    class AdversarialJudge:
        """Minimal fallback judge that returns a neutral verdict."""

        def __init__(self, *args, **kwargs):
            try:
                from internal.council.weights import load_weights
                self.weights = load_weights()
            except Exception:
                self.weights = {"quant": 0.25, "hype": 0.25, "dark_horse": 0.25, "technical": 0.25}

        def judge_decision(self, signal, outcome):
            consensus = float(signal.get("consensus_score", 0.5))
            action = signal.get("recommended_action", "hold")
            if action == "accumulate":
                label = "validated"
            elif action == "reduce":
                label = "contradicted"
            else:
                label = "neutral"
            return {"outcome_label": label, "confidence": round(consensus, 4), "note": "Fallback adversarial verdict."}

    class MindmapBridge:
        """Minimal fallback mindmap bridge that keeps state in memory."""

        def __init__(self, *args, **kwargs):
            self.soul_map_state = {}

        def _save_to_disk(self):
            pass

        def log_simivision_feedback(self, subnet_id, outcome, note=""):
            pass

logger = logging.getLogger(__name__)

class JuryBridge:
    """Bridge that transforms message analysis into signals the AdversarialJudge can evaluate."""

    def __init__(self, judge=None, mindmap=None):
        self.judge = judge or AdversarialJudge()
        self.mindmap = mindmap or MindmapBridge()

    def evaluate(self, message_id, content, analysis):
        signal = self._build_signal(message_id, content, analysis)
        outcome = self._build_outcome(analysis)
        verdict = self.judge.judge_decision(signal, outcome)
        result = self._map_verdict(verdict, analysis)
        self._update_mindmap(content, analysis, result)
        logger.info("Jury verdict for message %d: %s (conviction=%.2f)", message_id, result["verdict"], result["conviction"])
        return result

    def _build_signal(self, message_id, content, analysis):
        sentiment = analysis.get("sentiment", "neutral")
        hype = analysis.get("hype_score", 0.0)
        substance = analysis.get("substance_score", 0.0)
        influence = analysis.get("influence_score", 0.0)
        if sentiment == "bullish" and influence >= 0.5:
            action = "accumulate"
        elif sentiment == "bearish" and influence >= 0.5:
            action = "reduce"
        else:
            action = "hold"
        consensus_score = round((substance * 0.35 + (influence * 0.25) + (1.0 - hype * 0.3) * 0.2 + 0.2), 4)
        consensus_score = min(1.0, max(0.0, consensus_score))
        sentiment_map = {"bullish": 0.8, "bearish": 0.2, "neutral": 0.5}
        sentiment_score = sentiment_map.get(sentiment, 0.5)
        return {
            "subnet_id": None,
            "consensus_score": consensus_score,
            "recommended_action": action,
            "expert_breakdown": {
                "quant": {"score": substance, "metrics": {"substance_index": substance * 100}},
                "hype": {"score": hype, "sentiment": sentiment, "metrics": {"hype_index": hype * 100}},
                "dark_horse": {"score": 1.0 - sentiment_score, "signal": "sell" if sentiment == "bullish" else "buy", "metrics": {"dark_horse_index": (1.0 - sentiment_score) * 100}},
                "technical": {"score": influence, "signal": action, "metrics": {"influence_index": influence * 100}},
            },
        }

    @staticmethod
    def _build_outcome(analysis):
        hype = analysis.get("hype_score", 0.0)
        substance = analysis.get("substance_score", 0.0)
        influence = analysis.get("influence_score", 0.0)
        return {"status": "active", "emission": max(0.1, substance * 2.0), "social_mentions": int(influence * 2000), "is_overvalued": hype > 0.7 and substance < 0.3}

    @staticmethod
    def _map_verdict(jury_verdict, analysis):
        sentiment = analysis.get("sentiment", "neutral")
        influence = analysis.get("influence_score", 0.0)
        if sentiment == "bullish" and influence >= 0.4:
            predicted_direction = "up"
            predicted_magnitude = round(influence * 0.15, 4)
        elif sentiment == "bearish" and influence >= 0.4:
            predicted_direction = "down"
            predicted_magnitude = round(influence * 0.1, 4)
        else:
            predicted_direction = "neutral"
            predicted_magnitude = 0.0
        substance = analysis.get("substance_score", 0.0)
        if substance > 0.6 and influence > 0.6:
            predicted_timeframe = "1h-4h"
        elif substance > 0.4:
            predicted_timeframe = "4h-24h"
        else:
            predicted_timeframe = "24h-7d"
        base_confidence = jury_verdict.get("confidence", 0.5)
        predicted_confidence = round((base_confidence + influence) / 2.0, 4)
        label = jury_verdict.get("outcome_label", "neutral")
        verdict_str = {"validated": "bullish", "contradicted": "bearish", "neutral": "neutral"}.get(label, "neutral")
        return {"verdict": verdict_str, "conviction": round(base_confidence * 100, 2), "reasoning": jury_verdict.get("note", "Evaluated by adversarial jury."), "predicted_direction": predicted_direction, "predicted_magnitude": predicted_magnitude, "predicted_timeframe": predicted_timeframe, "predicted_confidence": predicted_confidence}

    def _update_mindmap(self, content, analysis, verdict):
        try:
            entities = analysis.get("entities", {})
            subnets = entities.get("subnets", [])
            mindmap_entry = {"type": "telegram_intel", "content_preview": content[:200], "sentiment": analysis.get("sentiment"), "hype_score": analysis.get("hype_score"), "substance_score": analysis.get("substance_score"), "verdict": verdict.get("verdict"), "conviction": verdict.get("conviction"), "predicted_direction": verdict.get("predicted_direction"), "entities": entities, "timestamp": datetime.now(timezone.utc).isoformat()}
            if not hasattr(self.mindmap, "soul_map_state"):
                return
            intel_log = self.mindmap.soul_map_state.setdefault("telegram_intel_log", [])
            intel_log.append(mindmap_entry)
            self.mindmap.soul_map_state["telegram_intel_log"] = intel_log[-200:]
            self.mindmap._save_to_disk()
            for subnet_str in subnets:
                numbers = re.findall(r"\d+", subnet_str)
                for num_str in numbers:
                    try:
                        subnet_id = int(num_str)
                        boost = 0.02 if verdict.get("verdict") == "bullish" else -0.02
                        self.mindmap.log_simivision_feedback(subnet_id=subnet_id, outcome=1 if boost > 0 else -1, note="Telegram intel: " + str(verdict.get("verdict")) + " (" + str(verdict.get("conviction", 0)) + "%)")
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            logger.warning("Failed to update mindmap: %s", e)
