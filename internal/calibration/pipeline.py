"""Retrain → Cert → Fire for council expert weights (Phase N)."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.deduplication import mark_duplicates_in_resolved
from internal.council.grading import direction_correct, hybrid_score, hybrid_score_status
from internal.council.resolver import PREDICTIONS_PATH, _normalize_expert
from internal.council.weights import DEFAULT_WEIGHTS, load_weights, save_weights

MIN_RESOLVED_SAMPLE = 30
CERT_BACKTEST_N = 50
WEIGHT_FLOOR = 0.3
WEIGHT_CEILING = 2.0
MAX_EXPERT_RATIO = 2.0

_retrain_lock = threading.Lock()
_retrain_in_progress = False

_EXCLUDED_STATUSES = frozenset({"duplicate", "expired", "ungradeable"})


class FireError(Exception):
    """Weight swap failed verification or IO."""


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: str, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def _load_calibration_state(soul_map_path: str) -> Dict[str, Any]:
    data = _load_json(soul_map_path, {})
    adv = data.get("adversarial_state")
    if not isinstance(adv, dict):
        return {}
    cal = adv.get("calibration")
    return dict(cal) if isinstance(cal, dict) else {}


def _save_calibration_state(
    patch: Dict[str, Any],
    *,
    soul_map_path: str,
) -> None:
    from internal.council.weights import _load_raw, _save_raw

    data = _load_raw(soul_map_path)
    adv = data.setdefault("adversarial_state", {})
    if not isinstance(adv, dict):
        adv = {}
        data["adversarial_state"] = adv
    cal = adv.setdefault("calibration", {})
    if not isinstance(cal, dict):
        cal = {}
        adv["calibration"] = cal
    cal.update(patch)
    history = cal.get("history")
    if not isinstance(history, list):
        history = []
    event = patch.get("last_event")
    if isinstance(event, dict):
        history = (history + [event])[-5:]
        cal["history"] = history
    _save_raw(data, soul_map_path)


def _gradeable_row(row: Dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    status = str(row.get("status", "")).lower()
    if status in _EXCLUDED_STATUSES:
        return False
    if row.get("outcome") in {"duplicate", "expired", "ungradeable"}:
        return False
    if row.get("correct") is None:
        return False
    actual = row.get("actual_pct")
    if actual is None:
        return False
    return _normalize_expert(row) is not None


def load_training_rows(
    predictions_path: str = PREDICTIONS_PATH,
) -> List[Dict[str, Any]]:
    """Load deduped gradeable resolved rows from post-J predictions store."""
    data = _load_json(
        predictions_path,
        {"predictions": [], "resolved": [], "stats": {}},
    )
    resolved = list(data.get("resolved") or [])
    resolved = mark_duplicates_in_resolved(resolved)
    return [row for row in resolved if _gradeable_row(row)]


def _compress_ratio(weights: Dict[str, float], max_ratio: float) -> Dict[str, float]:
    """Pull extremes toward mean until max/min <= max_ratio."""
    w = {k: float(v) for k, v in weights.items()}
    for _ in range(8):
        vals = list(w.values())
        if not vals:
            return w
        lo, hi = min(vals), max(vals)
        if lo <= 0 or hi / lo <= max_ratio:
            break
        mean = sum(vals) / len(vals)
        for name in w:
            w[name] = w[name] * 0.5 + mean * 0.5
    return {k: round(v, 4) for k, v in w.items()}


def compute_proposed_weights(
    rows: List[Dict[str, Any]],
    *,
    floor: float = WEIGHT_FLOOR,
    ceiling: float = WEIGHT_CEILING,
    max_ratio: float = MAX_EXPERT_RATIO,
) -> Dict[str, float]:
    """Laplace-smoothed per-expert accuracy scaled to [floor, ceiling]."""
    stats: Dict[str, Dict[str, int]] = {
        name: {"correct": 0, "total": 0} for name in DEFAULT_WEIGHTS
    }
    for row in rows:
        expert = _normalize_expert(row)
        if not expert or expert not in stats:
            continue
        try:
            actual_pct = float(row.get("actual_pct", 0) or 0)
        except (TypeError, ValueError):
            continue
        stats[expert]["total"] += 1
        if direction_correct(row, actual_pct):
            stats[expert]["correct"] += 1

    proposed: Dict[str, float] = {}
    span = ceiling - floor
    for name in DEFAULT_WEIGHTS:
        correct = stats[name]["correct"]
        total = stats[name]["total"]
        accuracy = (correct + 1) / (total + 2)
        proposed[name] = round(floor + accuracy * span, 4)

    proposed = _compress_ratio(proposed, max_ratio)
    for name in proposed:
        proposed[name] = round(
            max(floor, min(ceiling, proposed[name])),
            4,
        )
    return proposed


def _holdout_rows(rows: List[Dict[str, Any]], backtest_n: int) -> List[Dict[str, Any]]:
    def _sort_key(row: Dict[str, Any]) -> str:
        return str(row.get("resolved_at") or row.get("created_at") or "")

    ordered = sorted(rows, key=_sort_key)
    if backtest_n <= 0:
        return ordered
    return ordered[-backtest_n:]


def _cert_row_score(row: Dict[str, Any], actual_pct: float) -> float:
    """J4 phase 2: hybrid score for signal_impact rows when gated; else direction-only."""
    try:
        actual = float(actual_pct)
    except (TypeError, ValueError):
        return 0.0
    mag_src = str(row.get("magnitude_source") or "")
    if mag_src == "signal_impact":
        status = hybrid_score_status()
        if status.get("ready"):
            hs = hybrid_score(row, actual, sample_n=int(status.get("n") or 0))
            if hs is not None:
                return float(hs)
    return 1.0 if direction_correct(row, actual) else 0.0


def _weighted_accuracy(
    rows: List[Dict[str, Any]],
    weights: Dict[str, float],
) -> Optional[float]:
    num = 0.0
    den = 0.0
    for row in rows:
        expert = _normalize_expert(row)
        if not expert:
            continue
        try:
            actual_pct = float(row.get("actual_pct", 0) or 0)
        except (TypeError, ValueError):
            continue
        w = float(weights.get(expert, 1.0) or 1.0)
        den += w
        num += w * _cert_row_score(row, actual_pct)
    if den <= 0:
        return None
    return round(num / den, 4)


def _sanity_checks(weights: Dict[str, float]) -> List[str]:
    errors: List[str] = []
    if set(weights.keys()) != set(DEFAULT_WEIGHTS.keys()):
        errors.append("missing_canonical_experts")
    vals = [float(weights.get(k, 0) or 0) for k in DEFAULT_WEIGHTS]
    if any(v != v or v <= 0 for v in vals):  # NaN or non-positive
        errors.append("invalid_values")
    if vals and min(vals) < WEIGHT_FLOOR:
        errors.append("below_floor")
    if vals and max(vals) > WEIGHT_CEILING:
        errors.append("above_ceiling")
    if vals and min(vals) > 0 and max(vals) / min(vals) > MAX_EXPERT_RATIO + 1e-6:
        errors.append("ratio_exceeded")
    return errors


def certify_weights(
    proposed: Dict[str, float],
    rows: List[Dict[str, Any]],
    *,
    current: Optional[Dict[str, float]] = None,
    min_sample: int = MIN_RESOLVED_SAMPLE,
    backtest_n: int = CERT_BACKTEST_N,
) -> Dict[str, Any]:
    """Backtest + sanity; proposed must meet or beat current on holdout."""
    current = current or load_weights()
    holdout = _holdout_rows(rows, backtest_n)
    sanity_errors = _sanity_checks(proposed)
    proposed_accuracy = _weighted_accuracy(holdout, proposed)
    current_accuracy = _weighted_accuracy(holdout, current)
    hybrid_status = hybrid_score_status()
    signal_impact_n = sum(
        1 for row in holdout if str(row.get("magnitude_source") or "") == "signal_impact"
    )

    report: Dict[str, Any] = {
        "passed": False,
        "sample_size": len(rows),
        "holdout_size": len(holdout),
        "min_sample": min_sample,
        "proposed_accuracy": proposed_accuracy,
        "current_accuracy": current_accuracy,
        "sanity_errors": sanity_errors,
        "reason": None,
        "scoring_mode": "hybrid" if hybrid_status.get("ready") and signal_impact_n else "direction",
        "hybrid_ready": bool(hybrid_status.get("ready")),
        "signal_impact_holdout": signal_impact_n,
    }

    if sanity_errors:
        report["reason"] = "sanity_failed"
        return report
    if len(rows) < min_sample:
        report["reason"] = "insufficient_data"
        return report
    if proposed_accuracy is None or current_accuracy is None:
        report["reason"] = "no_gradeable_holdout"
        return report
    if proposed_accuracy < current_accuracy:
        report["reason"] = "accuracy_regression"
        return report

    report["passed"] = True
    report["reason"] = "ok"
    return report


def fire_weights(
    proposed: Dict[str, float],
    *,
    soul_map_path: str = "data/soul_map.json",
) -> Dict[str, float]:
    """Atomic swap with verify; rollback to backup on failure."""
    backup = load_weights(soul_map_path)
    save_weights(proposed, soul_map_path)
    verify = load_weights(soul_map_path)
    mismatch = any(
        abs(float(verify.get(k, 0) or 0) - float(proposed.get(k, 0) or 0)) > 1e-4
        for k in DEFAULT_WEIGHTS
    )
    if mismatch:
        save_weights(backup, soul_map_path)
        raise FireError("verify_failed_after_save")
    return verify


def _emit_retrain_trail(
    *,
    before: Dict[str, float],
    after: Optional[Dict[str, float]],
    cert: Dict[str, Any],
    fired: bool,
) -> None:
    try:
        from internal.learning.trail_events import emit_trail_event

        emit_trail_event(
            "weight_change",
            signal="calibration_retrain",
            evidence={
                "before": before,
                "after": after,
                "cert": cert,
                "fired": fired,
            },
            decision="retrain_fired" if fired else "cert_failed",
        )
    except Exception:
        pass


def run_calibration_pipeline(
    *,
    dry_run: bool = False,
    force: bool = False,
    soul_map_path: str = "data/soul_map.json",
    predictions_path: str = PREDICTIONS_PATH,
) -> Dict[str, Any]:
    """Run Retrain → Cert → Fire synchronously."""
    global _retrain_in_progress
    if not _retrain_lock.acquire(blocking=False):
        return {"status": "in_progress", "message": "retrain already running"}

    _retrain_in_progress = True
    started_at = _utcnow_z()
    backup = load_weights(soul_map_path)

    try:
        rows = load_training_rows(predictions_path)
        proposed = compute_proposed_weights(rows)
        cert = certify_weights(proposed, rows, current=backup)
        admin_token = os.environ.get("CALIBRATION_ADMIN_TOKEN")
        allow_force = force and not admin_token

        if dry_run:
            return {
                "status": "dry_run",
                "started_at": started_at,
                "proposed_weights": proposed,
                "cert": cert,
                "weights": backup,
                "would_fire": bool(cert.get("passed") or allow_force),
            }

        if not cert.get("passed") and not allow_force:
            event = {
                "at": started_at,
                "status": "cert_failed",
                "cert": cert,
                "proposed_weights": proposed,
            }
            _save_calibration_state(
                {
                    "last_retrain_at": started_at,
                    "last_cert_status": "failed",
                    "last_cert": cert,
                    "last_event": event,
                    "retrain_in_progress": False,
                },
                soul_map_path=soul_map_path,
            )
            _emit_retrain_trail(before=backup, after=None, cert=cert, fired=False)
            return {
                "status": "cert_failed",
                "started_at": started_at,
                "proposed_weights": proposed,
                "cert": cert,
                "weights": backup,
            }

        fired = fire_weights(proposed, soul_map_path=soul_map_path)
        event = {
            "at": started_at,
            "status": "fired",
            "cert": cert,
            "proposed_weights": proposed,
            "forced": allow_force,
        }
        _save_calibration_state(
            {
                "last_retrain_at": started_at,
                "last_cert_status": "passed" if cert.get("passed") else "forced",
                "last_cert": cert,
                "last_fired_weights": fired,
                "weights_backup": backup,
                "last_event": event,
                "retrain_in_progress": False,
            },
            soul_map_path=soul_map_path,
        )
        _emit_retrain_trail(before=backup, after=fired, cert=cert, fired=True)
        return {
            "status": "fired",
            "started_at": started_at,
            "fired_at": _utcnow_z(),
            "proposed_weights": proposed,
            "weights": fired,
            "cert": cert,
            "forced": allow_force,
        }
    except FireError as exc:
        _save_calibration_state(
            {
                "last_retrain_at": started_at,
                "last_cert_status": "fire_failed",
                "last_error": str(exc),
                "retrain_in_progress": False,
            },
            soul_map_path=soul_map_path,
        )
        return {
            "status": "fire_failed",
            "error": str(exc),
            "weights": load_weights(soul_map_path),
        }
    finally:
        _retrain_in_progress = False
        _retrain_lock.release()


def get_calibration_status(
    soul_map_path: str = "data/soul_map.json",
    predictions_path: str = PREDICTIONS_PATH,
) -> Dict[str, Any]:
    from internal.council.conviction_bands import conviction_bands_status
    from internal.council.grading import hybrid_score_status
    from internal.council.weights import load_impact_strength, load_weights

    cal = _load_calibration_state(soul_map_path)
    rows = load_training_rows(predictions_path)
    return {
        "status": "ok",
        "weights": load_weights(soul_map_path),
        "impact_strength": load_impact_strength(soul_map_path),
        "hybrid_score": hybrid_score_status(),
        "conviction_band": conviction_bands_status(),
        "calibration": {
            "last_retrain_at": cal.get("last_retrain_at"),
            "last_cert_status": cal.get("last_cert_status"),
            "last_cert": cal.get("last_cert"),
            "resolved_sample": len(rows),
            "retrain_in_progress": _retrain_in_progress,
            "auto_retrain_enabled": os.environ.get("CALIBRATION_AUTO_RETRAIN", "").lower()
            in {"1", "true", "on", "yes"},
            "history": cal.get("history", []),
            "impact_strength": {
                "value": load_impact_strength(soul_map_path),
                "range": [0.0, 2.0],
                "default": 1.0,
                "env_override": "IMPACT_STRENGTH",
                "meaning": "0=no size tilt, 1=default, 2=aggressive small-cap bias",
            },
        },
        "thresholds": {
            "min_sample": MIN_RESOLVED_SAMPLE,
            "backtest_n": CERT_BACKTEST_N,
            "weight_floor": WEIGHT_FLOOR,
            "weight_ceiling": WEIGHT_CEILING,
            "max_expert_ratio": MAX_EXPERT_RATIO,
        },
    }


def start_retrain_async(
    *,
    dry_run: bool = False,
    force: bool = False,
    soul_map_path: str = "data/soul_map.json",
    predictions_path: str = PREDICTIONS_PATH,
) -> Dict[str, Any]:
    """Non-blocking retrain for hot-path safety."""
    if _retrain_in_progress:
        return {"started": False, "in_progress": True, "reason": "already_running"}

    def _worker() -> None:
        run_calibration_pipeline(
            dry_run=dry_run,
            force=force,
            soul_map_path=soul_map_path,
            predictions_path=predictions_path,
        )

    threading.Thread(target=_worker, daemon=True, name="calibration-retrain").start()
    return {"started": True, "in_progress": True, "dry_run": dry_run}
