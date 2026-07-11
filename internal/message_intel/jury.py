"""Jury scoring for message-intel (works with stub AdversarialJudge)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _build_signal(content: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
    sentiment = analysis.get("sentiment", "neutral")
    hype = float(analysis.get("hype_score", 0.0) or 0)
    substance = float(analysis.get("substance_score", 0.0) or 0)
    influence = float(analysis.get("influence_score", 0.0) or 0)
    if sentiment == "bullish" and influence >= 0.5:
        action = "accumulate"
    elif sentiment == "bearish" and influence >= 0.5:
        action = "reduce"
    else:
        action = "hold"
    consensus_score = round((substance * 0.35 + influence * 0.25 + (1.0 - hype * 0.3) * 0.2 + 0.2), 4)
    consensus_score = min(1.0, max(0.0, consensus_score))
    return {
        "recommended_action": action,
        "consensus_score": consensus_score,
    }


def _map_verdict(analysis: Dict[str, Any], confidence: float) -> Dict[str, Any]:
    sentiment = analysis.get("sentiment", "neutral")
    influence = float(analysis.get("influence_score", 0.0) or 0)
    substance = float(analysis.get("substance_score", 0.0) or 0)
    if sentiment == "bullish" and influence >= 0.4:
        predicted_direction = "up"
        predicted_magnitude = round(influence * 0.15, 4)
    elif sentiment == "bearish" and influence >= 0.4:
        predicted_direction = "down"
        predicted_magnitude = round(influence * 0.1, 4)
    else:
        predicted_direction = "neutral"
        predicted_magnitude = 0.0
    if substance > 0.6 and influence > 0.6:
        predicted_timeframe = "1h-4h"
    elif substance > 0.4:
        predicted_timeframe = "4h-24h"
    else:
        predicted_timeframe = "24h-7d"
    predicted_confidence = round((confidence + influence) / 2.0, 4)
    verdict_str = {"bullish": "bullish", "bearish": "bearish"}.get(sentiment, "neutral")
    return {
        "verdict": verdict_str,
        "conviction": round(confidence * 100, 2),
        "reasoning": "Message-intel adversarial scoring from NLP features.",
        "predicted_direction": predicted_direction,
        "predicted_magnitude": predicted_magnitude,
        "predicted_timeframe": predicted_timeframe,
        "predicted_confidence": predicted_confidence,
    }


def evaluate_message(message_id: int, content: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Score a message and return a jury verdict dict."""
    signal = _build_signal(content, analysis)
    confidence = float(signal["consensus_score"])
    jury_label = "validated"
    if signal["recommended_action"] == "reduce":
        jury_label = "contradicted"
    elif signal["recommended_action"] == "hold":
        jury_label = "neutral"

    try:
        from internal.council.judge.adversarial import AdversarialJudge

        judge = AdversarialJudge()
        if hasattr(judge, "judge_decision"):
            outcome = {
                "status": "active",
                "emission": max(0.1, float(analysis.get("substance_score", 0)) * 2.0),
                "social_mentions": int(float(analysis.get("influence_score", 0)) * 2000),
                "is_overvalued": float(analysis.get("hype_score", 0)) > 0.7
                and float(analysis.get("substance_score", 0)) < 0.3,
            }
            raw = judge.judge_decision(signal, outcome)
            confidence = float(raw.get("confidence", confidence))
            label = raw.get("outcome_label", jury_label)
            verdict_str = {"validated": "bullish", "contradicted": "bearish", "neutral": "neutral"}.get(
                label, "neutral"
            )
            result = _map_verdict(analysis, confidence)
            result["verdict"] = verdict_str
            result["reasoning"] = raw.get("note", result["reasoning"])
            logger.info(
                "Jury verdict for message %d: %s (conviction=%.2f)",
                message_id,
                result["verdict"],
                result["conviction"],
            )
            return result
    except Exception as exc:
        logger.debug("AdversarialJudge unavailable, using NLP fallback: %s", exc)

    result = _map_verdict(analysis, confidence)
    logger.info(
        "Jury verdict for message %d: %s (conviction=%.2f)",
        message_id,
        result["verdict"],
        result["conviction"],
    )
    return result
