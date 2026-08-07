"""Daily calibration health snapshot for Telegram evidence.

Persists the calibration_health() dict to ``data/calibration_snapshots/``
and emits a warning when the calibration factor shifts by more than
``CALIBRATION_SNAPSHOT_DRIFT_EPSILON`` (default 0.01) compared with the
previous snapshot.  The snapshot is written atomically so readers never
see a partial file.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

SNAPSHOTS_DIR = os.environ.get(
    "CALIBRATION_SNAPSHOTS_DIR",
    os.path.join("data", "calibration_snapshots"),
)

# Warn when the calibration factor moves by more than this amount.
DEFAULT_DRIFT_EPSILON = 0.01


def _snapshots_dir() -> str:
    return os.environ.get("CALIBRATION_SNAPSHOTS_DIR", SNAPSHOTS_DIR)


def _drift_epsilon() -> float:
    try:
        return max(0.0, float(os.environ.get("CALIBRATION_SNAPSHOT_DRIFT_EPSILON", str(DEFAULT_DRIFT_EPSILON))))
    except ValueError:
        return DEFAULT_DRIFT_EPSILON


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _latest_path() -> str:
    return os.path.join(_snapshots_dir(), "latest.json")


def _snapshot_path(ts: Optional[str] = None) -> str:
    name = ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    return os.path.join(_snapshots_dir(), "snapshots", f"{name}.json")


def _read_json_if_exists(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.debug("calibration snapshot: could not read %s: %s", path, exc)
        return None


def _previous_factor() -> Optional[float]:
    """Return the calibration factor from the last persisted snapshot, or None."""
    prev = _read_json_if_exists(_latest_path())
    if prev is None:
        return None
    health = prev.get("calibration_health") or {}
    factor = health.get("factor")
    try:
        return float(factor)
    except (TypeError, ValueError):
        return None


def _check_drift(current_factor: float, previous_factor: Optional[float]) -> Tuple[bool, float]:
    """Return (drifted, delta) where drifted is True when |delta| > epsilon."""
    if previous_factor is None:
        return False, 0.0
    delta = abs(current_factor - previous_factor)
    return delta > _drift_epsilon(), round(delta, 6)


def build_calibration_snapshot(*, db=None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Collect the calibration health dict and annotate with drift information."""
    from internal.message_intel.calibration import calibration_health

    health = calibration_health(db=db, now=now)
    current_factor = float(health.get("factor") or 1.0)
    prev_factor = _previous_factor()
    drifted, delta = _check_drift(current_factor, prev_factor)

    drift_info: Dict[str, Any] = {
        "previous_factor": prev_factor,
        "current_factor": current_factor,
        "delta": delta,
        "epsilon": _drift_epsilon(),
        "drifted": drifted,
    }

    if drifted:
        logger.warning(
            "calibration snapshot: factor drift detected  previous=%.4f  current=%.4f  delta=%.6f  epsilon=%.6f",
            prev_factor,
            current_factor,
            delta,
            _drift_epsilon(),
        )

    alert_level = "warn" if drifted or not health.get("active") else "ok"
    alert_reasons: list = []
    if drifted:
        alert_reasons.append(
            f"factor_drift delta={delta:.6f} (previous={prev_factor}, current={current_factor})"
        )
    for reason in health.get("withheld_reasons") or []:
        alert_reasons.append(reason)

    return {
        "status": "ok",
        "captured_at": _utcnow_iso(),
        "alert_level": alert_level,
        "alert_reasons": alert_reasons,
        "drift": drift_info,
        "calibration_health": health,
    }


def save_snapshot(payload: Dict[str, Any]) -> str:
    """Persist *payload* to the timestamped snapshot file and update ``latest.json``."""
    base = _snapshots_dir()
    os.makedirs(os.path.join(base, "snapshots"), exist_ok=True)
    path = _snapshot_path()
    latest = _latest_path()
    for target in (path, latest):
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, target)
    return path


def run_calibration_snapshot(*, save: bool = True, db=None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Build and optionally persist the calibration snapshot.  Returns the payload."""
    payload = build_calibration_snapshot(db=db, now=now)
    if save:
        payload["path"] = save_snapshot(payload)
    return payload
