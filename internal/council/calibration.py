"""
Calibration / precision curve for the Council engine.

Bins resolved predictions by confidence threshold and tracks whether precision
rises with confidence (TaoDX-style calibration). Snapshots persist to
``data/calibration.json`` for historical tracking.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

CALIBRATION_PATH = os.path.join("data", "calibration.json")
PREDICTIONS_PATH = os.path.join("data", "predictions.json")

_BIN_EDGES = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _prediction_confidence(prediction: Dict[str, Any]) -> float:
    """Return a 0-1 confidence value for a prediction."""
    confidence = prediction.get("confidence")
    if isinstance(confidence, (int, float)) and 0 <= confidence <= 1:
        return float(confidence)

    predicted_pct = float(prediction.get("predicted_pct", 0) or 0)
    return min(abs(predicted_pct) / 100.0, 1.0)


def compute_calibration_curve(
    predictions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Bin resolved predictions by confidence and compute precision per bin.

    Args:
        predictions: List of resolved predictions. Each prediction should
            contain ``correct`` (bool) and either ``confidence`` (0-1) or
            ``predicted_pct`` so confidence can be derived.

    Returns:
        Dict with ``curve`` (list of bin dicts), ``monotonic``,
        ``mean_precision`` and ``last_updated``.
    """
    bins: List[Dict[str, Any]] = []
    for i in range(len(_BIN_EDGES) - 1):
        start = _BIN_EDGES[i]
        end = _BIN_EDGES[i + 1]
        bins.append({
            "bin_label": f"{int(start * 100)}-{int(end * 100)}%",
            "threshold_start": start,
            "threshold_end": end,
            "total": 0,
            "correct": 0,
            "precision": 0.0,
        })

    total_correct = 0
    total_predictions = 0

    for pred in predictions:
        if pred.get("status") != "resolved":
            continue
        confidence = _prediction_confidence(pred)
        correct = bool(pred.get("correct"))

        for b in bins:
            if b["threshold_start"] <= confidence < b["threshold_end"]:
                b["total"] += 1
                if correct:
                    b["correct"] += 1
                break
        else:
            # Confidence == 1.0 falls into the last bin.
            bins[-1]["total"] += 1
            if correct:
                bins[-1]["correct"] += 1

        total_predictions += 1
        if correct:
            total_correct += 1

    for b in bins:
        if b["total"] > 0:
            b["precision"] = round(b["correct"] / b["total"], 4)

    mean_precision = round(total_correct / total_predictions, 4) if total_predictions > 0 else 0.0

    snapshot = {
        "curve": bins,
        "monotonic": get_monotonicity_score(bins),
        "mean_precision": mean_precision,
        "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    _save_json(CALIBRATION_PATH, snapshot)
    return snapshot


def get_monotonicity_score(curve: List[Dict[str, Any]]) -> bool:
    """Return True if precision is non-decreasing with confidence."""
    precisions = [b["precision"] for b in curve if b["total"] > 0]
    if len(precisions) < 2:
        return True
    return all(precisions[i] <= precisions[i + 1] for i in range(len(precisions) - 1))


def get_calibration_snapshot() -> Dict[str, Any]:
    """Return the latest persisted calibration snapshot."""
    snapshot = _load_json(
        CALIBRATION_PATH,
        {
            "curve": [
                {
                    "bin_label": f"{int(_BIN_EDGES[i] * 100)}-{int(_BIN_EDGES[i + 1] * 100)}%",
                    "threshold_start": _BIN_EDGES[i],
                    "threshold_end": _BIN_EDGES[i + 1],
                    "total": 0,
                    "correct": 0,
                    "precision": 0.0,
                }
                for i in range(len(_BIN_EDGES) - 1)
            ],
            "monotonic": True,
            "mean_precision": 0.0,
            "last_updated": None,
        },
    )
    snapshot.setdefault("monotonic", get_monotonicity_score(snapshot.get("curve", [])))
    return snapshot


def load_resolved_predictions(path: str = PREDICTIONS_PATH) -> List[Dict[str, Any]]:
    """Load resolved predictions from the predictions ledger."""
    data = _load_json(path, {"predictions": [], "resolved": []})
    return list(data.get("resolved", []))


def recalibrate(path: str = PREDICTIONS_PATH) -> Dict[str, Any]:
    """Recompute and persist the calibration curve from the prediction ledger."""
    predictions = load_resolved_predictions(path)
    return compute_calibration_curve(predictions)
