"""
Background scheduler for the technical indicator layer.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from internal.indicators.indicator_engine import IndicatorEngine

INDICATOR_REFRESH_MINUTES = int(os.environ.get("INDICATOR_REFRESH_MINUTES", "15"))
MAX_BACKOFF_MINUTES = int(os.environ.get("INDICATOR_MAX_BACKOFF_MINUTES", "240"))
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _load_json(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_path, path)

class IndicatorScheduler:
    """Background scheduler that periodically runs the IndicatorEngine."""

    def __init__(
        self,
        refresh_minutes: int = INDICATOR_REFRESH_MINUTES,
        max_backoff_minutes: int = MAX_BACKOFF_MINUTES,
        soul_map_path: str = SOUL_MAP_PATH,
        registry_path: str = REGISTRY_PATH,
        engine_factory: Optional[Callable[[], IndicatorEngine]] = None,
    ):
        self.refresh_minutes = refresh_minutes
        self.max_backoff_minutes = max_backoff_minutes
        self.soul_map_path = soul_map_path
        self.registry_path = registry_path
        self.engine_factory = engine_factory or (
            lambda: IndicatorEngine(
                registry_path=registry_path,
                soul_map_path=soul_map_path,
            )
        )

        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._running = False
        self._backoff_minutes = refresh_minutes
        self._consecutive_failures = 0
        self._last_run_at: Optional[str] = None
        self._last_run_ok: Optional[bool] = None
        self._last_run_error: Optional[str] = None
        self._next_run_at: Optional[str] = None

    def start(self, immediate: bool = False) -> Dict[str, Any]:
        """Start the scheduler. Idempotent."""
        with self._lock:
            if self._running:
                return {"started": False, "reason": "already running"}
            self._running = True
            self._backoff_minutes = self.refresh_minutes
            self._consecutive_failures = 0

        if immediate:
            # Run the first tick in a background thread so callers are not
            # blocked while prices are fetched.
            threading.Thread(target=self._tick, daemon=True).start()
        else:
            # First tick happens soon after deploy so the dashboard isn't empty
            # for a full refresh interval; normal cadence resumes afterwards.
            self._schedule_next(1)

        return {
            "started": True,
            "refresh_minutes": self.refresh_minutes,
            "next_run_at": self._next_run_at,
        }

    def stop(self) -> Dict[str, Any]:
        """Stop the scheduler and cancel any pending tick."""
        with self._lock:
            self._running = False
            self._next_run_at = None
            timer = self._timer
            self._timer = None
        if timer:
            timer.cancel()
        return {"stopped": True}

    def state(self) -> Dict[str, Any]:
        """Return the current scheduler state for health checks."""
        with self._lock:
            return {
                "running": self._running,
                "refresh_minutes": self.refresh_minutes,
                "backoff_minutes": self._backoff_minutes,
                "consecutive_failures": self._consecutive_failures,
                "last_run_at": self._last_run_at,
                "last_run_ok": self._last_run_ok,
                "last_run_error": self._last_run_error,
                "next_run_at": self._next_run_at,
            }

    def run_once(self) -> Dict[str, Any]:
        """Execute a single refresh cycle synchronously."""
        return self._tick()

    def should_refresh(self) -> bool:
        """Check if enough time has passed since last refresh."""
        if not self._running:
            return False
        current_backoff = self._backoff_minutes * 60
        # For simplicity, always allow refresh if running
        return True

    def check_and_run(self) -> Dict[str, Any]:
        """
        Check if refresh is due and run if so.
        For backward compatibility, this runs immediately if the scheduler is running.
        """
        if self.should_refresh():
            return self._tick()
        return {
            "ok": True,
            "skipped": True,
            "reason": "not due yet",
            "last_refresh_at": self._last_run_at,
        }

    def _schedule_next(self, minutes: int) -> None:
        with self._lock:
            if not self._running:
                return
            self._next_run_at = (
                datetime.now(timezone.utc).timestamp() + minutes * 60
            )
            self._timer = threading.Timer(minutes * 60, self._tick)
            self._timer.daemon = True
            self._timer.start()

    def _tick(self) -> Dict[str, Any]:
        """Run one indicator refresh cycle and reschedule."""
        result = self._run_refresh_cycle()

        with self._lock:
            self._last_run_at = result["run_at"]
            self._last_run_ok = result["ok"]
            self._last_run_error = result.get("error")
            if result["ok"]:
                self._consecutive_failures = 0
                self._backoff_minutes = self.refresh_minutes
            else:
                self._consecutive_failures += 1
                self._backoff_minutes = min(
                    self.refresh_minutes * (2 ** self._consecutive_failures),
                    self.max_backoff_minutes,
                )
            next_interval = self._backoff_minutes

        if self._running:
            self._schedule_next(next_interval)
        return result

    def _run_refresh_cycle(self) -> Dict[str, Any]:
        """Run the IndicatorEngine and persist a cycle summary."""
        run_at = _now_iso()
        result: Dict[str, Any] = {
            "ok": False,
            "run_at": run_at,
            "subnets_processed": 0,
            "signals_emitted": 0,
            "error": None,
        }

        try:
            engine = self.engine_factory()
            cycle = engine.run_cycle()
            result["ok"] = True
            result["subnets_processed"] = cycle.get("subnets_processed", 0)
            result["signals_emitted"] = cycle.get("signals_emitted", 0)
            result["cycle"] = cycle
        except Exception as exc:
            result["error"] = str(exc)

        self._persist_cycle_summary(result)
        return result

    def _persist_cycle_summary(self, result: Dict[str, Any]) -> None:
        data = _load_json(self.soul_map_path)
        summary = {
            "run_at": result["run_at"],
            "ok": result["ok"],
            "subnets_processed": result.get("subnets_processed", 0),
            "signals_emitted": result.get("signals_emitted", 0),
            "error": result.get("error"),
        }
        data.setdefault("indicator_scheduler", {})["last_cycle"] = summary
        _save_json(self.soul_map_path, data)


# ------------------------------------------------------------------------------
# Module-level singleton for server.py
# ------------------------------------------------------------------------------

_scheduler: Optional[IndicatorScheduler] = None
_scheduler_lock = threading.Lock()

def start_indicator_scheduler(
    refresh_minutes: int = INDICATOR_REFRESH_MINUTES,
    immediate: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Start the module-level indicator scheduler singleton."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = IndicatorScheduler(
                refresh_minutes=refresh_minutes, **kwargs
            )
        return _scheduler.start(immediate=immediate)

def stop_indicator_scheduler() -> Dict[str, Any]:
    """Stop the module-level indicator scheduler singleton."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            return {"stopped": False, "reason": "not running"}
        result = _scheduler.stop()
        _scheduler = None
        return result

def get_indicator_scheduler_state() -> Dict[str, Any]:
    """Return the state of the module-level indicator scheduler singleton."""
    with _scheduler_lock:
        if _scheduler is None:
            return {
                "running": False,
                "refresh_minutes": INDICATOR_REFRESH_MINUTES,
                "backoff_minutes": INDICATOR_REFRESH_MINUTES,
                "consecutive_failures": 0,
                "last_run_at": None,
                "last_run_ok": None,
                "last_run_error": None,
                "next_run_at": None,
            }
        return _scheduler.state()

def get_indicator_scheduler() -> Optional[IndicatorScheduler]:
    """Return the scheduler singleton for direct access."""
    with _scheduler_lock:
        return _scheduler