"""
Adversarial Scheduler (The Learning Loop)

REFRESH_MINUTES-configurable background scheduler. The legacy Selector /
AdversarialJudge cycle was removed during the council hygiene pass; the
scheduler now persists a lightweight heartbeat and registry snapshot to the
Soul-Map on each tick.

Health reporting goes exclusively through the LivenessTracker (issue #1032):
"ok" is never a stored value, always derived from last_success_at freshness.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from internal.job_scheduler import cancel_job, schedule_in_seconds
from internal.store.soul_map_io import write_soul_map
from internal.liveness import LivenessTracker

try:
    from internal.file_utils import ensure_data_dir
    ensure_data_dir()
except Exception:
    os.makedirs('data', exist_ok=True)

REFRESH_MINUTES = int(os.environ.get("REFRESH_MINUTES", "60"))
MAX_BACKOFF_MINUTES = int(os.environ.get("MAX_BACKOFF_MINUTES", "240"))
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")
JOB_ID = "adversarial-scheduler"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: str):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


class AdversarialScheduler:
    """Background scheduler that records heartbeat + registry snapshot.

    Health is reported exclusively through the LivenessTracker (issue #1032);
    "ok" is never stored, always derived from the tracker's success age.
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
        self.stake_threshold_tao = stake_threshold_tao

        self._lock = threading.Lock()
        self._active = False
        self._backoff_minutes = refresh_minutes
        self._consecutive_failures = 0
        self._last_run_timestamp: float = 0.0
        self._last_run_error: Optional[str] = None
        self._next_run_at: Optional[float] = None
        self._state_cache: Dict[str, Any] = {}
        self._last_subnet_count: int = 0
        self.liveness = LivenessTracker(
            name="adversarial_scheduler",
            interval_seconds=max(60, int(refresh_minutes) * 60),
            staleness_factor=2,
            persist=True,
        )

    def start(self, immediate: bool = False) -> Dict[str, Any]:
        with self._lock:
            if self._active:
                return {"started": False, "reason": "already running"}
            self._active = True
            self._backoff_minutes = self.refresh_minutes
            self._consecutive_failures = 0
            self._last_run_timestamp = time.time()
        self.liveness.start()
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
        with self._lock:
            self._active = False
            self._next_run_at = None
        cancel_job(JOB_ID)
        return {"stopped": True}

    def _liveness_ok(self) -> bool:
        return self.liveness.snapshot()["status"] == "ok"

    def state(self) -> Dict[str, Any]:
        with self._lock:
            snap = self.liveness.snapshot()
            return {
                "running": self._active,
                "refresh_minutes": self.refresh_minutes,
                "backoff_minutes": self._backoff_minutes,
                "consecutive_failures": self._consecutive_failures,
                "last_run_at": snap.get("last_event_at"),
                "last_run_ok": self._liveness_ok(),
                "last_run_error": self._last_run_error,
                "next_run_at": self._next_run_at,
                "last_subnet_count": self._last_subnet_count,
                "liveness": snap,
            }

    def run_once(self) -> Dict[str, Any]:
        return self._tick()

    def should_refresh(self) -> bool:
        if not self._active:
            return False
        return (time.time() - self._last_run_timestamp) >= self._backoff_minutes * 60

    def check_and_run(self) -> Dict[str, Any]:
        if self.should_refresh():
            return self._tick()
        self.liveness.record_skip("not due yet")
        return {
            "skipped": True,
            "reason": "not due yet",
            "status": self.liveness.snapshot()["status"],
            "last_refresh_at": self.liveness.snapshot().get("last_event_at"),
        }

    def _schedule_next(self, minutes: int) -> None:
        with self._lock:
            if not self._active:
                return
            self._next_run_at = time.time() + minutes * 60
        schedule_in_seconds(JOB_ID, self._tick, minutes * 60)

    def _tick(self) -> Dict[str, Any]:
        result = self._run_refresh_cycle()
        with self._lock:
            self._last_run_timestamp = time.time()
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
        if result["ok"]:
            self.liveness.record_success(evidence={
                "registry_subnet_count": self._last_subnet_count,
                "op": "adversarial_refresh",
            })
        else:
            self.liveness.record_failure(result.get("error") or "refresh cycle failed")
        if self._active:
            self._schedule_next(self._backoff_minutes)
        return result

    def _run_refresh_cycle(self) -> Dict[str, Any]:
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

    def _persist_cycle_summary(self, run_at: str, registry: Dict[str, Any]) -> None:
        summary = {"run_at": run_at, "registry_subnet_count": len(registry)}
        self._state_cache = summary
        try:
            from internal.council.emission_monitor import snapshot_registry_emissions
            emissions = snapshot_registry_emissions(registry, run_at=run_at)
        except Exception:
            emissions = {}
        try:
            try:
                from internal.file_utils import ensure_data_dir
                ensure_data_dir()
            except Exception:
                os.makedirs(os.path.dirname(self.soul_map_path) or "data", exist_ok=True)
            def _mutator(blob: Dict[str, Any]) -> None:
                blob.setdefault("adversarial_scheduler", {})["last_cycle"] = summary
                if emissions:
                    blob.setdefault("emission_monitor", {})["last_emissions"] = emissions
                    blob["emission_monitor"]["snapshot_at"] = run_at
            write_soul_map(_mutator, self.soul_map_path)
        except Exception:
            pass


_scheduler = None


def get_adversarial_scheduler() -> AdversarialScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AdversarialScheduler()
    return _scheduler


def start_adversarial_scheduler(immediate: bool = False) -> Dict[str, Any]:
    return get_adversarial_scheduler().start(immediate=immediate)


def get_adversarial_scheduler_state() -> Dict[str, Any]:
    return get_adversarial_scheduler().state()
