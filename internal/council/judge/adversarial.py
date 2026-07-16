"""
Adversarial Judge (The Feedback Loop)

Scores message/council signals against observed outcomes for jury bridges.
"""

from __future__ import annotations

from typing import Any, Dict


class AdversarialJudge:
    def __init__(self, persist: bool = True):
        self.persist = persist
        try:
            from internal.council.weights import load_weights

            self.weights = load_weights()
        except Exception:
            self.weights = {
                "quant": 0.25,
                "hype": 0.25,
                "dark_horse": 0.25,
                "technical": 0.25,
            }

    def judge_decision(self, signal: Dict[str, Any], outcome: Dict[str, Any]) -> Dict[str, Any]:
        """Return outcome_label + confidence for jury / message-intel bridges."""
        action = str(signal.get("recommended_action", "hold")).lower()
        try:
            consensus = float(signal.get("consensus_score", 0.5) or 0.5)
        except (TypeError, ValueError):
            consensus = 0.5
        overvalued = bool(outcome.get("is_overvalued"))
        try:
            emission = float(outcome.get("emission", 0) or 0)
        except (TypeError, ValueError):
            emission = 0.0

        if action in {"accumulate", "buy", "long"} and not overvalued:
            label = "validated"
        elif action in {"reduce", "sell", "short"} or overvalued:
            label = "contradicted"
        else:
            label = "neutral"

        boost = 1.05 if label == "validated" else 0.92 if label == "contradicted" else 1.0
        if emission > 1.0:
            boost *= 1.02
        confidence = min(1.0, max(0.0, consensus * boost))
        return {
            "outcome_label": label,
            "confidence": round(confidence, 4),
            "note": "Adversarial jury verdict from signal vs outcome.",
        }


if __name__ == "__main__":
    judge = AdversarialJudge(persist=False)
    out = judge.judge_decision(
        {"recommended_action": "accumulate", "consensus_score": 0.7},
        {"emission": 1.2, "is_overvalued": False},
    )
    assert out["outcome_label"] == "validated"
    print("adversarial judge self-check ok")
