"""
Background scheduler for the prediction resolver (the learning loop's judge).

The resolver logic lives in :mod:`internal.council.resolver`; this module is
the *scheduler* that runs it on a clock so predictions get graded even when no
dashboard is being rendered (e.g. Fly.io auto-stop, headless deployments).

Each tick:
1. Fetches the latest subnet snapshot (price feed).
2. Calls ``resolver.resolve_due_predictions`` to grade due predictions and
   nudge Council expert weights via the learning loop.
3. Calls ``resolver.expire_stale_predictions`` to retire predictions that are
   past due with no resolvable price (delisted subnet / feed outage / corrupt
   record) so the registry never accumulates ungradeable ``pending`` rows.
4. Persists a lightweight cycle summary to the Soul-Map for health checks.

Follows the same ``threading.Timer`` + exponential-backoff pattern as the
indicator scheduler so it is safe for single-worker Fly.io deployments.
"""

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from internal.council import resolver

# Ensure the data directory exists at module load time. Fly.io root filesystems
# are ephemeral; without this the cycle-summary write below silently fails.
try:
    from internal.file_utils import ensure_data_dir
    ensure_data_dir()
except Exception:  # pragma: no cover - keep import-safe if file_utils is unavailable
    os.makedirs("data", exist_ok=True)

RESOLVER_REFRESH_MINUTES = int(os.environ.get("RESOLVER_REFRESH_MINUTES", "15"))
MAX_BACKOFF_MINUTES = int(os.environ.get("RESOLVER_MAX_BACKOFF_MINUTES", "240"))
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")


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
    try:
        from internal.file_utils import ensure_data_dir
        ensure_data_dir()
    except Exception:
        os.makedirs(os.path.dirname(path) or "data", exist_ok=True)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


class PredictionResolverScheduler:
    """Background scheduler that periodically grades pending predictions."""

    def __init__(
        self,
        refresh_minutes: int = RESOLVER_REFRESH_MINUTES,
        max_backoff_minutes: int = MAX_BACKOFF_MINUTES,
        soul_map_path: Optional[str] = None,
        subnet_provider: Optional[Callable[[], Any]] = None,
    ):
        self.refresh_minutes = refresh_minutes
        self.max_backoff_minutes = max_backoff_minutes
        # Resolve lazily so tests can monkeypatch the module-level
        # ``SOUL_MAP_PATH`` after import (mirrors resolver.py / weights.py).
        self._soul_map_path = soul_map_path
        # Pluggable subnet feed so tests can inject deterministic prices. The
        # default lazily imports server._get_subnets_with_source to avoid a
        # circular import at module load time.
        self._subnet_provider = subnet_provider or _default_subnets

        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._running = False
        self._backoff_minutes = refresh_minutes
        self._consecutive_failures = 0
        self._last_run_at: Optional[str] = None
        self._last_run_ok: Optional[bool] = None
        self._last_run_error: Optional[str] = None
        self._next_run_at: Optional[float] = None
        self._last_resolved = 0
        self._last_expired = 0
        self._last_pending = 0

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
            # blocked while prices are fetched and predictions are graded.
            threading.Thread(target=self._tick, daemon=True).start()
        else:
            # First tick happens soon after boot so a backlog of pending
            # predictions is cleared quickly; normal cadence resumes after.
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

    @property
    def soul_map_path(self) -> str:
        """Resolve the soul-map path lazily so tests can monkeypatch the
        module-level ``SOUL_MAP_PATH`` after import."""
        return self._soul_map_path or SOUL_MAP_PATH

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
                "last_resolved": self._last_resolved,
                "last_expired": self._last_expired,
                "last_pending": self._last_pending,
            }

    def run_once(self) -> Dict[str, Any]:
        """Execute a single resolution cycle synchronously."""
        return self._tick()

    def should_refresh(self) -> bool:
        if not self._running:
            return False
        return True

    def check_and_run(self) -> Dict[str, Any]:
        """Run a cycle if the scheduler is running (request-triggered refresh)."""
        if self.should_refresh():
            return self._tick()
        return {
            "ok": True,
            "skipped": True,
            "reason": "not running",
            "last_run_at": self._last_run_at,
        }

    def _schedule_next(self, minutes: int) -> None:
        with self._lock:
            if not self._running:
                return
            self._next_run_at = time.time() + minutes * 60
            self._timer = threading.Timer(minutes * 60, self._tick)
            self._timer.daemon = True
            self._timer.start()

    def _tick(self) -> Dict[str, Any]:
        """Run one resolution cycle and reschedule."""
        result = self._run_refresh_cycle()

        with self._lock:
            self._last_run_at = result["run_at"]
            self._last_run_ok = result["ok"]
            self._last_run_error = result.get("error")
            self._last_resolved = result.get("resolved_now", 0)
            self._last_expired = result.get("expired_now", 0)
            self._last_pending = result.get("pending", 0)
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
        """Grade due predictions, expire stale ones, persist a cycle summary."""
        run_at = _now_iso()
        result: Dict[str, Any] = {
            "ok": False,
            "run_at": run_at,
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
            "error": None,
        }

        try:
            subnets = self._subnet_provider() or []

            # 1. Grade predictions whose horizon has elapsed against the live
            #    price feed. This also nudges expert weights (learning loop).
            #    ``resolve_due_predictions`` itself retires predictions that are
            #    past due with no price as ``expired`` (correct=None), so we
            #    count those here too.
            resolved = resolver.resolve_due_predictions(subnets)
            result["resolved_now"] = len(resolved.get("resolved_now", []))
            expired_count = len(resolved.get("expired_now", []))

            # 2. Safety net: retire any predictions that are past due with no
            #    resolvable price so the registry never fills with ungradeable
            #    ``pending`` rows (delisted subnet / feed outage / corrupt row).
            #    Most are already retired in step 1; this catches stragglers
            #    (e.g. corrupt records that step 1 skipped).
            expired = resolver.expire_stale_predictions()
            expired_count += len(expired.get("expired_now", []))
            result["expired_now"] = expired_count
            result["pending"] = expired.get("stats", {}).get("pending", 0)
            result["watchdog"] = resolved.get("watchdog") or expired.get("watchdog")

            result["ok"] = True
            result["stats"] = expired.get("stats", resolved.get("stats", {}))
        except Exception as exc:
            result["error"] = str(exc)

        self._persist_cycle_summary(result)
        return result

    def _persist_cycle_summary(self, result: Dict[str, Any]) -> None:
        summary = {
            "run_at": result["run_at"],
            "ok": result["ok"],
            "resolved_now": result.get("resolved_now", 0),
            "expired_now": result.get("expired_now", 0),
            "pending": result.get("pending", 0),
            "error": result.get("error"),
            "watchdog": result.get("watchdog"),
        }
        data = _load_json(self.soul_map_path)
        data.setdefault("prediction_resolver_scheduler", {})["last_cycle"] = summary
        try:
            _save_json(self.soul_map_path, data)
        except Exception:
            pass


def _default_subnets() -> Any:
    """Return the live subnet snapshot, falling back to an empty list.

    Imported lazily so this module never creates a circular import with
    ``server`` (which imports the scheduler on startup).
    """
    try:
        from server import _get_subnets_with_source

        subnets, _ = _get_subnets_with_source()
        return subnets
    except Exception:
        return []


# ------------------------------------------------------------------------------
# Module-level singleton for server.py
# ------------------------------------------------------------------------------

_scheduler: Optional[PredictionResolverScheduler] = None
_scheduler_lock = threading.Lock()


def start_prediction_resolver_scheduler(
    refresh_minutes: int = RESOLVER_REFRESH_MINUTES,
    immediate: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Start the module-level prediction resolver scheduler singleton."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = PredictionResolverScheduler(
                refresh_minutes=refresh_minutes, **kwargs
            )
    result = _scheduler.start(immediate=immediate)
    try:
        from internal.council.selector_scheduler import start_selector_scheduler

        start_selector_scheduler(immediate=False)
    except Exception:
        pass
    try:
        from internal.pump.scheduler import start_pump_ladder_scheduler

        start_pump_ladder_scheduler(immediate=False)
    except Exception:
        pass
    return result


def stop_prediction_resolver_scheduler() -> Dict[str, Any]:
    """Stop the module-level prediction resolver scheduler singleton."""
    try:
        from internal.council.selector_scheduler import stop_selector_scheduler

        stop_selector_scheduler()
    except Exception:
        pass
    global _scheduler
    sched: Optional[PredictionResolverScheduler] = None
    with _scheduler_lock:
        sched = _scheduler
        _scheduler = None
    if sched is None:
        return {"stopped": False, "reason": "not running"}
    return sched.stop()


def get_prediction_resolver_scheduler_state() -> Dict[str, Any]:
    """Return the state of the module-level prediction resolver scheduler."""
    with _scheduler_lock:
        if _scheduler is None:
            return {
                "running": False,
                "refresh_minutes": RESOLVER_REFRESH_MINUTES,
                "backoff_minutes": RESOLVER_REFRESH_MINUTES,
                "consecutive_failures": 0,
                "last_run_at": None,
                "last_run_ok": None,
                "last_run_error": None,
                "next_run_at": None,
                "last_resolved": 0,
                "last_expired": 0,
                "last_pending": 0,
            }
        return _scheduler.state()


def get_prediction_resolver_scheduler() -> Optional[PredictionResolverScheduler]:
    """Return the scheduler singleton for direct access."""
    with _scheduler_lock:
        return _scheduler
