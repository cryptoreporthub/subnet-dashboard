"""
Adversarial Scheduler (The Learning Loop)

REFRESH_MINUTES-configurable background scheduler that drives the
outcome-driven adversarial intelligence layer.

Features:
- Configurable refresh interval via REFRESH_MINUTES environment variable.
- Exponential backoff on repeated failures (capped at max_backoff_minutes).
- Persists learned state to the Soul-Map (data/soul_map.json).
- Idempotent start/stop semantics safe for Fly.io single-worker deployments.
- Request-triggered refresh for Fly.io auto-stop compatibility.
- Filters subnets by total_stake to focus on low-mid cap subnets.
"""

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from internal.council.judge.adversarial import AdversarialJudge

# Ensure the data directory exists at module load time.
os.makedirs('data', exist_ok=True)
from internal.council.mindmap_bridge import MindmapBridge
from internal.council.selector import Selector

REFRESH_MINUTES = int(os.environ.get("REFRESH_MINUTES", "60"))
MAX_BACKOFF_MINUTES = int(os.environ.get("MAX_BACKOFF_MINUTES", "240"))
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")
# Exclude subnets with total_stake >= 450,000 TAO (top ~40 by market cap)
STAKE_THRESHOLD_TAO = float(os.environ.get("STAKE_THRESHOLD_TAO", "450000"))

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
    Background scheduler that periodically runs the Selector, judges the
    resulting decisions against the current registry outcomes, and persists
    the learned weights/verdicts back to the Soul-Map.
    
    Supports both timer-based (legacy) and request-triggered refresh modes.
    """

    def __init__(
        self,
        refresh_minutes: int = REFRESH_MINUTES,
        max_backoff_minutes: int = MAX_BACKOFF_MINUTES,
        soul_map_path: str = SOUL_MAP_PATH,
        registry_path: str = REGISTRY_PATH,
        stake_threshold_tao: float = STAKE_THRESHOLD_TAO,
        judge_factory: Optional[Callable[[], AdversarialJudge]] = None,
        selector_factory: Optional[Callable[[], Selector]] = None,
    ):
        self.refresh_minutes = refresh_minutes
        self.max_backoff_minutes = max_backoff_minutes
        self.soul_map_path = soul_map_path
        self.registry_path = registry_path
        self.stake_threshold_tao = stake_threshold_tao
        self.judge_factory = judge_factory or (
            lambda: AdversarialJudge(
                persistence_path=soul_map_path,
                registry_path=registry_path,
                persist=True,
            )
        )
        self.selector_factory = selector_factory or (
            lambda: Selector(
                mindmap_bridge=MindmapBridge(
                    persistence_path=soul_map_path,
                    registry_path=registry_path
                )
            )
        )

        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._running = False
        self._backoff_minutes = refresh_minutes
        self._consecutive_failures = 0
        self._last_run_at: Optional[str] = None
        self._last_run_timestamp: float = 0.0  # Epoch time for time-based checks
        self._last_run_ok: Optional[bool] = None
        self._last_run_error: Optional[str] = None
        self._next_run_at: Optional[float] = None  # Epoch time
        self._state_cache: Dict[str, Any] = {}  # In-memory fallback
        self._last_subnet_count: int = 0

    # ------------------------------------------------------------------
    # Public control API
    # ------------------------------------------------------------------
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
        required_seconds = self._backoff_minutes * 60
        
        # Allow refresh if enough time has elapsed (or never run)
        return elapsed >= required_seconds

    def check_and_run(self) -> Dict[str, Any]:
        """
        Check if refresh is due and run if so.
        This is the primary entry point for request-triggered refreshes.
        """
        if self.should_refresh():
            return self._tick()
        return {
            "ok": True,
            "skipped": True,
            "reason": "not due yet",
            "last_refresh_at": self._last_run_at,
        }

    # ------------------------------------------------------------------
    # Internal tick
    # ------------------------------------------------------------------
    def _schedule_next(self, minutes: int) -> None:
        """Schedule the next timer-based tick. May be called even if running=False."""
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
            next_interval = self._backoff_minutes

        if self._running:
            self._schedule_next(next_interval)
        return result

    def _filter_low_mid_cap_subnets(
        self, registry: Dict[str, Any]
    ) -> List[int]:
        """
        Filter registry to only include low-mid cap subnets.
        Excludes subnets with total_stake >= threshold (default: 450,000 TAO).
        """
        subnet_ids = []
        for sid_str, data in registry.items():
            try:
                stake = data.get("staking_data", {}).get("total_stake", 0)
                if stake < self.stake_threshold_tao:
                    subnet_ids.append(int(sid_str))
            except (ValueError, TypeError):
                # Include subnets with missing/invalid stake data
                subnet_ids.append(int(sid_str))
        return subnet_ids

    def _run_refresh_cycle(self) -> Dict[str, Any]:
        """
        Run the Selector across the registry, judge each decision against the
        current registry outcome, and persist learned state.
        """
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

            selector = self.selector_factory()
            judge = self.judge_factory()

            # Filter to low-mid cap subnets only
            subnet_ids = self._filter_low_mid_cap_subnets(registry)
            self._last_subnet_count = len(subnet_ids)
            
            context_map = {
                sid: {
                    "emission": registry.get(str(sid), {}).get("emission", 0.0),
                    "social_mentions": registry.get(str(sid), {}).get(
                        "social_mentions", 0
                    ),
                    "is_overvalued": registry.get(str(sid), {}).get(
                        "is_overvalued", False
                    ),
                }
                for sid in subnet_ids
            }

            rotation = selector.process_daily_rotation(subnet_ids, context_map)
            decisions = rotation.get("daily_output", {}).get("decisions", [])

            verdicts: List[Dict[str, Any]] = []
            for decision in decisions:
                sid = decision.get("subnet_id")
                outcome = context_map.get(sid, {})
                outcome["status"] = registry.get(str(sid), {}).get("status", "unknown")
                verdict = judge.judge_outcome_only(sid, decision, outcome)
                verdicts.append(verdict)

            # Persist a summary of this refresh cycle into the Soul-Map.
            self._persist_cycle_summary(run_at, verdicts, judge.get_council_weights())

            result["ok"] = True
            result["decisions_judged"] = len(verdicts)
            result["verdicts"] = verdicts
        except Exception as exc:
            result["error"] = str(exc)

        return result

    def _persist_cycle_summary(
        self, run_at: str, verdicts: List[Dict[str, Any]], weights: Dict[str, float]
    ) -> None:
        """Persist cycle summary to file with in-memory fallback."""
        summary = {
            "run_at": run_at,
            "verdict_count": len(verdicts),
            "mean_score": round(
                sum(v.get("score", 0.0) for v in verdicts) / len(verdicts), 4
            )
            if verdicts
            else 0.0,
            "mean_confidence": round(
                sum(v.get("confidence", 0.0) for v in verdicts) / len(verdicts), 4
            )
            if verdicts
            else 0.0,
            "council_weights": weights,
        }
        
        # Always update in-memory cache
        self._state_cache = summary
        
        # Try to persist to file, but don't fail if we can't
        try:
            data: Dict[str, Any] = {}
            if os.path.exists(self.soul_map_path):
                data = _load_json(self.soul_map_path) or {}

            data.setdefault("adversarial_scheduler", {})["last_cycle"] = summary

            dir_name = os.path.dirname(self.soul_map_path)
            os.makedirs(dir_name, exist_ok=True)

            # Write to unique temp file first, then rename for atomicity
            fd, temp_path = tempfile.mkstemp(dir=dir_name or ".", suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(data, f, indent=2)
                os.replace(temp_path, self.soul_map_path)
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
        except Exception:
            # Silently continue with in-memory state
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