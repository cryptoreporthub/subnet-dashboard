"""
Adversarial Scheduler (The Learning Loop)

REFRESH_MINUTES-configurable background scheduler that drives the
outcome-driven adversarial intelligence layer.

Features:
- Configurable refresh interval via REFRESH_MINUTES environment variable.
- Exponential backoff on repeated failures (capped at max_backoff_minutes).
- Persists learned state to the Soul-Map (data/soul_map.json).
- Idempotent start/stop semantics safe for Fly.io single-worker deployments.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from internal.council.judge.adversarial import AdversarialJudge
from internal.council.mindmap_bridge import MindmapBridge
from internal.council.selector import Selector

REFRESH_MINUTES = int(os.environ.get("REFRESH_MINUTES", "60"))
MAX_BACKOFF_MINUTES = int(os.environ.get("MAX_BACKOFF_MINUTES", "240"))
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")

class AdversarialScheduler:
    """
    Background scheduler that periodically runs the Selector, judges the
    resulting decisions against the current registry outcomes, and persists
    the learned weights/verdicts back to the Soul-Map.
    """

    def __init__(
        self,
        refresh_minutes: int = REFRESH_MINUTES,
        max_backoff_minutes: int = MAX_BACKOFF_MINUTES,
        soul_map_path: str = SOUL_MAP_PATH,
        registry_path: str = REGISTRY_PATH,
        judge_factory: Optional[Callable[[], AdversarialJudge]] = None,
        selector_factory: Optional[Callable[[], Selector]] = None,
    ):
        self.refresh_minutes = refresh_minutes
        self.max_backoff_minutes = max_backoff_minutes
        self.soul_map_path = soul_map_path
        self.registry_path = registry_path
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
        self._last_run_ok: Optional[bool] = None
        self._last_run_error: Optional[str] = None
        self._next_run_at: Optional[str] = None

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
            }

    def run_once(self) -> Dict[str, Any]:
        """Execute a single refresh cycle synchronously."""
        return self._tick()

    # ------------------------------------------------------------------
    # Internal tick
    # ------------------------------------------------------------------
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
        """Run one adversarial refresh cycle and reschedule."""
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

            subnet_ids = [int(k) for k in registry.keys()]
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
        data: Dict[str, Any] = {}
        if os.path.exists(self.soul_map_path):
            try:
                with open(self.soul_map_path, "r") as f:
                    data = json.load(f)
            except Exception:
                data = {}

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
        data.setdefault("adversarial_scheduler", {})["last_cycle"] = summary

        dir_name = os.path.dirname(self.soul_map_path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        temp_path = self.soul_map_path + ".tmp"
        with open(temp_path, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, self.soul_map_path)

# ------------------------------------------------------------------------------
# Module-level singleton for server.py
# ------------------------------------------------------------------------------

_scheduler: Optional[AdversarialScheduler] = None
_scheduler_lock = threading.Lock()

def start_adversarial_scheduler(
    refresh_minutes: int = REFRESH_MINUTES,
    immediate: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Start the module-level scheduler singleton."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = AdversarialScheduler(
                refresh_minutes=refresh_minutes, **kwargs
            )
        return _scheduler.start(immediate=immediate)

def stop_adversarial_scheduler() -> Dict[str, Any]:
    """Stop the module-level scheduler singleton."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            return {"stopped": False, "reason": "not running"}
        result = _scheduler.stop()
        _scheduler = None
        return result

def get_adversarial_scheduler_state() -> Dict[str, Any]:
    """Return the state of the module-level scheduler singleton."""
    with _scheduler_lock:
        if _scheduler is None:
            return {
                "running": False,
                "refresh_minutes": REFRESH_MINUTES,
                "backoff_minutes": REFRESH_MINUTES,
                "consecutive_failures": 0,
                "last_run_at": None,
                "last_run_ok": None,
                "last_run_error": None,
                "next_run_at": None,
            }
        return _scheduler.state()

def get_adversarial_scheduler() -> Optional[AdversarialScheduler]:
    """Return the scheduler singleton for direct access."""
    with _scheduler_lock:
        return _scheduler

def _load_json(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()