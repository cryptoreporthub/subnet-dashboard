"""
Fixed daily retrain scheduler for the Council engine.

Runs once daily at a configurable UTC hour, resolves due 24h predictions,
recomputes the calibration curve, archives the cycle to
``data/retrain_history.json`` and updates the learning loop.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from internal.council import calibration, resolver, weights

RETRAIN_HISTORY_PATH = os.path.join("data", "retrain_history.json")


class RetrainScheduler:
    """Background scheduler for the daily Council retrain cycle."""

    def __init__(
        self,
        hour_utc: int = 0,
        minute_utc: int = 0,
        predictions_path: Optional[str] = None,
        history_path: Optional[str] = None,
    ):
        if not (0 <= hour_utc <= 23):
            raise ValueError("hour_utc must be 0-23")
        if not (0 <= minute_utc <= 59):
            raise ValueError("minute_utc must be 0-59")

        self.hour_utc = hour_utc
        self.minute_utc = minute_utc
        self.predictions_path = predictions_path or resolver.PREDICTIONS_PATH
        self.history_path = history_path or RETRAIN_HISTORY_PATH

        self._last_retrain: Optional[str] = None
        self._last_report: Optional[Dict[str, Any]] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def _load_json(self, path: str, default: Any) -> Any:
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return default

    def _save_json(self, path: str, data: Any) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)

    def _next_run_time(self, after: Optional[datetime] = None) -> datetime:
        """Compute the next scheduled run time in UTC."""
        now = after or datetime.now(timezone.utc)
        candidate = now.replace(hour=self.hour_utc, minute=self.minute_utc, second=0, microsecond=0)
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        return candidate

    def _archive_report(self, report: Dict[str, Any]) -> None:
        """Append a retrain report to the history archive."""
        history = self._load_json(self.history_path, {"cycles": []})
        if not isinstance(history, dict):
            history = {"cycles": []}
        history.setdefault("cycles", []).append(report)
        # Keep the archive from growing unbounded.
        history["cycles"] = history["cycles"][-365:]
        history["last_updated"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._save_json(self.history_path, history)

    def run_cycle(self, subnets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Execute one retrain cycle now and return a RetrainReport."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat().replace("+00:00", "Z")

        # 1. Resolve due predictions.
        resolution = resolver.resolve_due_predictions(subnets)
        resolved_now = resolution.get("resolved_now", [])
        stats = resolution.get("stats", {})
        accuracy = stats.get("accuracy", 0.0)
        predictions_resolved = len(resolved_now)

        # 2. Recompute calibration curve.
        curve_snapshot = calibration.recalibrate(self.predictions_path)

        # 3. Capture weights snapshot.
        weights_snapshot = weights.load_weights()

        report: Dict[str, Any] = {
            "timestamp": now_iso,
            "predictions_resolved": predictions_resolved,
            "accuracy": accuracy,
            "precision_curve": curve_snapshot.get("curve", []),
            "monotonic": curve_snapshot.get("monotonic", True),
            "mean_precision": curve_snapshot.get("mean_precision", 0.0),
            "weights_snapshot": weights_snapshot,
        }

        self._archive_report(report)

        with self._lock:
            self._last_retrain = now_iso
            self._last_report = report

        return report

    def _loop(self) -> None:
        """Background loop that waits for the next scheduled run."""
        while not self._stop_event.is_set():
            next_run = self._next_run_time()
            sleep_seconds = (next_run - datetime.now(timezone.utc)).total_seconds()
            if sleep_seconds > 0:
                # Wake up every minute to check for stop events promptly.
                if self._stop_event.wait(timeout=min(sleep_seconds, 60.0)):
                    break
                continue

            try:
                self.run_cycle()
            except Exception:
                # Log and continue; the next cycle will retry tomorrow.
                pass

            # Sleep until after the next scheduled time to avoid double runs.
            self._stop_event.wait(timeout=60.0)

    def start(self) -> None:
        """Start the background scheduler thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background scheduler thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def get_status(self) -> Dict[str, Any]:
        """Return scheduler status: last retrain, next retrain, last report."""
        with self._lock:
            last_retrain = self._last_retrain
            last_report = self._last_report

        next_run = self._next_run_time(
            datetime.fromisoformat(last_retrain.replace("Z", "+00:00")) if last_retrain else None
        )

        return {
            "last_retrain": last_retrain,
            "next_retrain": next_run.isoformat().replace("+00:00", "Z"),
            "last_report": last_report,
            "hour_utc": self.hour_utc,
            "minute_utc": self.minute_utc,
        }

    def trigger_now(self, subnets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Manually trigger a retrain cycle and return the report."""
        return self.run_cycle(subnets)
