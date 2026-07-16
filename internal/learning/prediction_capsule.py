"""§21 L12 — time-capsule replay: full prediction snapshot by id."""

from __future__ import annotations

from typing import Any, Dict, Optional

_SKIP = frozenset({"duplicate", "expired", "ungradeable"})


def _find_prediction(prediction_id: str) -> Optional[Dict[str, Any]]:
    from internal.learning.predictions_store import load_predictions

    data = load_predictions()
    for bucket in ("resolved", "predictions"):
        for pred in data.get(bucket) or []:
            if isinstance(pred, dict) and str(pred.get("id") or "") == str(prediction_id):
                row = dict(pred)
                row["_bucket"] = bucket
                return row
    return None


def build_share_card(pred: Dict[str, Any]) -> str:
    """Plain-text graded call card for clipboard share (§21 L14 lite)."""
    name = pred.get("name") or f"SN{pred.get('netuid', '?')}"
    predicted = pred.get("predicted_pct")
    actual = pred.get("actual_pct")
    outcome = "✓" if pred.get("correct") else "✗" if pred.get("correct") is False else "?"
    lines = [
        f"SimiVision graded call — {name}",
        f"Prediction: {pred.get('statement') or '—'}",
    ]
    if predicted is not None and actual is not None:
        lines.append(f"Expected {float(predicted):+.1f}% → actual {float(actual):+.1f}% {outcome}")
    snap = pred.get("subnet_snapshot") if isinstance(pred.get("subnet_snapshot"), dict) else {}
    if snap.get("yield_trap"):
        lines.append("Context: yield trap (high APY, falling token)")
    driver = snap.get("return_driver") or snap.get("dominant_driver")
    if driver:
        lines.append(f"Driver: {str(driver).replace('_', ' ')}")
    lines.append("— subnet-dashboard / SimiVision learning loop")
    return "\n".join(lines)


def get_prediction_capsule(prediction_id: str) -> Dict[str, Any]:
    """Return full prediction + replay capsule for time-travel UI."""
    pred = _find_prediction(prediction_id)
    if not pred:
        return {"status": "not_found", "reason": "unknown_id"}

    snap = pred.get("subnet_snapshot") if isinstance(pred.get("subnet_snapshot"), dict) else {}
    bucket = pred.pop("_bucket", None)
    gradeable = pred.get("outcome") not in _SKIP and pred.get("actual_pct") is not None

    return {
        "status": "success",
        "prediction_id": prediction_id,
        "bucket": bucket,
        "gradeable": gradeable,
        "prediction": pred,
        "capsule": {
            "statement": pred.get("statement"),
            "expert": pred.get("expert"),
            "horizon_type": pred.get("horizon_type"),
            "created_at": pred.get("created_at"),
            "resolved_at": pred.get("resolved_at"),
            "predicted_pct": pred.get("predicted_pct"),
            "actual_pct": pred.get("actual_pct"),
            "correct": pred.get("correct"),
            "subnet_snapshot": snap,
            "active_signals": pred.get("active_signals"),
            "weights_at_creation": pred.get("weights_at_creation"),
            "judge_scores_at_creation": pred.get("judge_scores_at_creation"),
            "learning_state_at_creation": pred.get("learning_state_at_creation"),
        },
        "share_text": build_share_card(pred),
    }
