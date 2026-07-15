"""Env-gated post-resolver auto-retrain hook (Phase N3)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.calibration import pipeline as cal_pipeline
from internal.calibration.pipeline import (
    MIN_RESOLVED_SAMPLE,
    start_retrain_async,
)

_AUTO_ON = frozenset({"1", "true", "on", "yes"})
_last_hook: Dict[str, Any] = {"last_run_at": None, "triggered": False, "reason": "never_run"}


def auto_retrain_enabled() -> bool:
    return os.environ.get("CALIBRATION_AUTO_RETRAIN", "").lower() in _AUTO_ON


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _rows_since_last_retrain(
    rows: List[Dict[str, Any]],
    last_retrain_at: Optional[str],
) -> int:
    if not last_retrain_at:
        return len(rows)
    return sum(
        1
        for row in rows
        if str(row.get("resolved_at") or row.get("created_at") or "") > last_retrain_at
    )


def maybe_trigger_auto_retrain(*, resolved_now: int = 0) -> Dict[str, Any]:
    """Post-resolver hook; non-blocking when enabled."""
    run_at = _utcnow_z()
    soul_path = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
    result: Dict[str, Any] = {
        "last_run_at": run_at,
        "triggered": False,
        "enabled": auto_retrain_enabled(),
        "resolved_this_cycle": resolved_now,
    }

    if not auto_retrain_enabled():
        result["reason"] = "disabled"
        _last_hook.update(result)
        return result

    cal = cal_pipeline._load_calibration_state(soul_path)
    last_retrain = cal.get("last_retrain_at")
    pred_path = os.environ.get("PREDICTIONS_PATH", cal_pipeline.PREDICTIONS_PATH)
    rows = cal_pipeline.load_training_rows(pred_path)
    total = len(rows)
    result["sample_total"] = total

    if total < MIN_RESOLVED_SAMPLE:
        result["reason"] = "insufficient_total_sample"
        _last_hook.update(result)
        return result

    since_count = _rows_since_last_retrain(rows, last_retrain)
    result["resolved_since_last_retrain"] = since_count
    min_new = int(
        os.environ.get("CALIBRATION_AUTO_RETRAIN_MIN_NEW", str(MIN_RESOLVED_SAMPLE))
    )
    if since_count < min_new:
        result["reason"] = "below_new_resolution_threshold"
        result["min_new_required"] = min_new
        _last_hook.update(result)
        return result

    async_result = start_retrain_async(
        dry_run=False,
        force=False,
        soul_map_path=soul_path,
        predictions_path=pred_path,
    )
    result["triggered"] = bool(async_result.get("started"))
    result["reason"] = (
        "started" if result["triggered"] else async_result.get("reason", "skipped")
    )
    result["async"] = async_result
    _last_hook.update(result)
    return result


def get_auto_retrain_hook_status() -> Dict[str, Any]:
    return dict(_last_hook)
