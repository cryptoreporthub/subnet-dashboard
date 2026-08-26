"""Slice 7b — read-only online weight path audit (no soul_map writes)."""

from __future__ import annotations

from typing import Any, Dict, List

from internal.council.weights import DEFAULT_WEIGHTS, load_weights
from internal.judges.weights import DEFAULT_JUDGE_WEIGHTS, normalized_judge_weights

_KNOWN_GAPS: List[Dict[str, Any]] = [
    {
        "id": "judge-pump-shadow",
        "severity": "P2",
        "detail": "Judge nudges skip pump/shadow rows (mirrors council skip).",
        "fixed": True,
    },
    {
        "id": "streaks-mixed-pop",
        "severity": "P1",
        "detail": "Streak whisper counts council_trust-published rows only.",
        "fixed": True,
    },
    {
        "id": "combined-frozen",
        "severity": "info",
        "detail": "Combined 0.70/0.30 weights frozen until soak GO + graded_30d >= 20.",
    },
]


def _post_flip_drift_watch(expert_weights: Dict[str, float]) -> Dict[str, Any]:
    """7-day post Phase B watch: alert if any expert/signal crosses ratio 2.0."""
    alerts: List[str] = []
    for name, val in (expert_weights or {}).items():
        try:
            if abs(float(val)) >= 2.0 - 1e-9:
                alerts.append(f"expert:{name}={val}")
        except (TypeError, ValueError):
            continue
    try:
        from internal.council.weights import load_signal_weights

        signals = load_signal_weights()
        for horizon, bucket in (signals or {}).items():
            if not isinstance(bucket, dict):
                continue
            for sig, val in bucket.items():
                try:
                    if abs(float(val)) >= 2.0 - 1e-9:
                        alerts.append(f"signal:{horizon}:{sig}={val}")
                except (TypeError, ValueError):
                    continue
    except Exception:
        pass
    return {
        "window_days": 7,
        "ratio_alert": 2.0,
        "includes_signal_weights": True,
        "alerts": alerts,
    }


def _recent_resolve_population(limit: int = 100) -> Dict[str, int]:
    try:
        from internal.accuracy_lift.populations import population_of
        from internal.learning.predictions_store import load_predictions

        resolved = load_predictions().get("resolved") or []
        graded = [
            row
            for row in resolved[-limit:]
            if isinstance(row, dict) and row.get("correct") is not None
        ]
        counts: Dict[str, int] = {}
        for row in graded:
            bucket = population_of(row)
            counts[bucket] = counts.get(bucket, 0) + 1
        return counts
    except Exception:
        return {}


def build_weight_audit_report() -> Dict[str, Any]:
    """Online-path inventory for ops evidence — archive replay excluded."""
    expert_weights = load_weights()
    judge_weights = normalized_judge_weights()
    return {
        "read_only": True,
        "online_path": {
            "expert": (
                "resolver._stamp_and_nudge_expert -> nudge_expert -> "
                "soul_map adversarial_state.council_weights"
            ),
            "judge": (
                "judges.tracker.on_prediction_resolved -> nudge_judge -> "
                "soul_map judge_weights"
            ),
            "calibration": "calibration.pipeline (cert-gated; dry_run unless certified)",
            "archive_replay_in_prod": False,
        },
        "expert_weights": expert_weights,
        "judge_weights": judge_weights,
        "defaults": {
            "expert": dict(DEFAULT_WEIGHTS),
            "judge": dict(DEFAULT_JUDGE_WEIGHTS),
        },
        "nudge_constants": {
            "correct_delta": 0.02,
            "wrong_delta": -0.03,
            "symmetric_clamp": [0.1, 2.0],
        },
        "combined_weights_frozen": True,
        "recent_resolve_population": _recent_resolve_population(),
        "known_gaps": list(_KNOWN_GAPS),
        "post_flip_drift_watch": _post_flip_drift_watch(expert_weights),
        "tune_gate": {
            "published_graded_30d_min": 20,
            "recommendation": "HOLD weight/calibration tune until soak GO and published sample clears gate.",
        },
    }
