"""
Standalone judge_decision function for the orchestrator verdict loop.

This module provides a lightweight, importable judge_decision function
that can be called by the orchestrator without instantiating the full
AdversarialJudge class (which has persistence side-effects).
"""

from datetime import datetime, timezone


def judge_decision(pick):
    """
    Evaluate a single selector decision and return a verdict dict.

    Args:
        pick: A decision dict from the selector (must have at least
              'recommended_action' and 'consensus_score').

    Returns:
        dict with keys: timestamp, confidence, dissent, reasoning, verdict
    """
    action = pick.get("recommended_action", "hold")
    consensus = pick.get("consensus_score", 0.5) or 0.5

    # Confidence is derived from consensus extremity and action clarity.
    extremity = abs(consensus - 0.5) * 2.0
    if action == "hold":
        confidence = 0.5 + extremity * 0.2
    else:
        confidence = 0.5 + extremity * 0.4

    confidence = round(min(1.0, max(0.0, confidence)), 4)

    # Dissent is true when consensus is weak or action is hold.
    dissent = consensus < 0.55 or action == "hold"

    # Build a human-readable reasoning string.
    if action == "accumulate":
        reasoning = f"Accumulate signal with consensus {consensus:.2f}"
    elif action == "reduce":
        reasoning = f"Reduce signal with consensus {consensus:.2f}"
    else:
        reasoning = f"Hold signal with consensus {consensus:.2f}"

    # Verdict label: aligned when confidence >= 0.6, divergent when < 0.4.
    if confidence >= 0.6:
        verdict = "aligned"
    elif confidence < 0.4:
        verdict = "divergent"
    else:
        verdict = "neutral"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "confidence": confidence,
        "dissent": dissent,
        "reasoning": reasoning,
        "verdict": verdict,
    }