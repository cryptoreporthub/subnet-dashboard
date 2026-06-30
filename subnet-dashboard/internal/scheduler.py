"""
Adversarial Scheduler (The Learning Loop)

REFRESH_MINUTES-configurable background scheduler. The legacy Selector /
AdversarialJudge cycle was removed during the council hygiene pass; the
scheduler now persists a lightweight heartbeat and registry snapshot to the
Soul-Map on each tick.

Features:
- Configurable refresh interval via REFRESH_MINUTES environment variable.
- Exponential backoff on repeated failures (capped at max_backoff_minutes).
- Persists heartbeat to the Soul-Map (data/soul_map.json).
- Idempotent start/stop semantics safe for Fly.io single-worker deployments.
- Request-triggered refresh for Fly.io auto-stop compatibility.
"""

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Ensure the data directory exists at module load time.
os.makedirs('data', exist_ok=True)

REFRESH_MINUTES = int(os.environ.get("REFRESH_MINUTES", "60"))
MAX_BACKOFF_MINUTES = int(os.environ.get("MAX_BACKOFF_MINUTES", "240"))
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")

def _now_iso() -> str:
    """Return current UTC time as ISO format string."""
    return datetime.now(timezone.utc).isoformat()

def _load_json(path: str) -> Optional[Dict[str, Any]]:
    """Load JSON file, return None if missing or invalid."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None

class AdversarialScheduler:
    """
    Background scheduler that periodically records a lightweight heartbeat and
    registry snapshot. The legacy Selector/AdversarialJudge cycle was removed
    during the council hygiene pass.

    Supports both timer-based (legacy) and request-triggered refresh modes.
    """

    def __init__(
        self,
        refresh_minutes: int = REFRESH_MINUTES,
        max_backoff_minutes: int = MAX_BACKOFF_MINUTES,
        soul_map_path: str = SOUL_MAP_PATH,
        registry_path: str = REGISTRY_PATH,
        stake_threshold_tao: float = 400000.0,
    ):
        self.refresh_minutes = refresh_minutes
        self.max_backoff_minutes = max_backoff_minutes
        self.soul_map_path = soul_map_path
        self.registry_path = registry_path
        # stake_threshold_tao kept for API compatibility but no longer used.
        self.stake_threshold_tao = stake_threshold_tao

        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._running = False
        self._backoff_minutes = refresh_minutes
        self._consecutive_failures = 0
        self._last_run_at: Optional[str] = None
        self._last_run_timestamp: float = 0.0
        self._last_run_ok: Optional[bool] = None
        self._last_run_error: Optional[str] = None
        self._next_run_at: Optional[float] = None
        self._state_cache: Dict[str, Any] = {}
        self._last_subnet_count: int = 0

    def start(self, immediate: bool = False) -> Dict[str, Any]:
        """Start the scheduler. Idempotent."""
        with self._lock:
            if self._running:
                return {"started": False, "reason": "already running"}
            self._running = True
            self._backoff_minutes = self.refresh_minutes
            self._consecutive_failures = 0
            self._last_run_timestamp = time.time()

        if immediate:
            self._tick()
        else:
            self._schedule_next(self.refresh_minutes)

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
                "last_subnet_count": self._last_subnet_count,
            }

    def run_once(self) -> Dict[str, Any]:
        """Execute a single refresh cycle synchronously."""
        return self._tick()

    def should_refresh(self) -> bool:
        """Check if enough time has passed since last refresh."""
        if not self._running:
            return False
        current_time = time.time()
        elapsed = current_time - self._last_run_timestamp
        return elapsed >= self._backoff_minutes * 60

    def check_and_run(self) -> Dict[str, Any]:
        """Check if refresh is due and run if so."""
        if self.should_refresh():
            return self._tick()
        return {
            "ok": True,
            "skipped": True,
            "reason": "not due yet",
            "last_refresh_at": self._last_run_at,
        }

    def _schedule_next(self, minutes: int) -> None:
        """Schedule the next timer-based tick."""
        with self._lock:
            if not self._running:
                return
            self._next_run_at = time.time() + minutes * 60
            self._timer = threading.Timer(minutes * 60, self._tick)
            self._timer.daemon = True
            self._timer.start()

    def _tick(self) -> Dict[str, Any]:
        """Run one adversarial refresh cycle and reschedule."""
        result = self._run_refresh_cycle()

        with self._lock:
            self._last_run_at = result["run_at"]
            self._last_run_timestamp = time.time()
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

        if self._running:
            self._schedule_next(self._backoff_minutes)
        return result

    def _run_refresh_cycle(self) -> Dict[str, Any]:
        """Record a lightweight heartbeat and registry snapshot."""
        run_at = _now_iso()
        result = {
            "ok": False,
            "run_at": run_at,
            "decisions_judged": 0,
            "verdicts": [],
            "error": None,
        }

        try:
            registry = _load_json(self.registry_path)
            if not registry:
                raise RuntimeError("registry is empty or missing")

            self._last_subnet_count = len(registry)
            self._persist_cycle_summary(run_at, registry)

            result["ok"] = True
            result["decisions_judged"] = 0
        except Exception as exc:
            result["error"] = str(exc)

        return result

    def _persist_cycle_summary(
        self, run_at: str, registry: Dict[str, Any]
    ) -> None:
        """Persist a lightweight heartbeat to the Soul-Map."""
        summary = {
            "run_at": run_at,
            "registry_subnet_count": len(registry),
        }
        self._state_cache = summary
        try:
            data: Dict[str, Any] = {}
            if os.path.exists(self.soul_map_path):
                data = _load_json(self.soul_map_path) or {}
            data.setdefault("adversarial_scheduler", {})["last_cycle"] = summary
            os.makedirs(os.path.dirname(self.soul_map_path) or ".", exist_ok=True)
            fd, temp_path = tempfile.mkstemp(suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(data, f, indent=2)
                os.replace(temp_path, self.soul_map_path)
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
        except Exception:
            pass

# ------------------------------------------------------------------------------
# Module-level singleton for server.py
# ------------------------------------------------------------------------------

_scheduler: Optional[AdversarialScheduler] = None

def get_adversarial_scheduler() -> AdversarialScheduler:
    """Get or create the module-level scheduler singleton."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AdversarialScheduler()
    return _scheduler

def start_adversarial_scheduler(immediate: bool = False) -> Dict[str, Any]:
    """Start the adversarial scheduler (module-level helper)."""
    return get_adversarial_scheduler().start(immediate=immediate)

def get_adversarial_scheduler_state() -> Dict[str, Any]:
    """Get the scheduler state (module-level helper)."""
    return get_adversarial_scheduler().state()