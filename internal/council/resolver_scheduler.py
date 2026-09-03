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

Follows the same APScheduler + exponential-backoff pattern as the
indicator scheduler so it is safe for single-worker Fly.io deployments.
"""

import json
import logging
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, Optional

from internal.council import resolver
from internal.job_scheduler import cancel_job, schedule_in_seconds
from internal.store.soul_map_io import write_soul_map

from internal.liveness import LivenessTracker

logger = logging.getLogger(__name__)

# Ensure the data directory exists at module load time. Fly.io root filesystems
# are ephemeral; without this the cycle-summary write below silently fails.
try:
    from internal.file_utils import ensure_data_dir
    ensure_data_dir()
except Exception:  # pragma: no cover - keep import-safe if file_utils is unavailable
    os.makedirs("data", exist_ok=True)

RESOLVER_REFRESH_MINUTES = int(os.environ.get("RESOLVER_REFRESH_MINUTES", "15"))
MAX_BACKOFF_MINUTES = int(os.environ.get("RESOLVER_MAX_BACKOFF_MINUTES", "240"))
RESOLVER_BATCH_SIZE = int(os.environ.get("RESOLVER_BATCH_SIZE", "32"))
RESOLVER_CYCLE_TIMEOUT_SECONDS = int(os.environ.get("RESOLVER_CYCLE_TIMEOUT_SECONDS", "120"))
RESOLVER_FIRST_TICK_DELAY_SECONDS = max(
    0, int(os.environ.get("RESOLVER_FIRST_TICK_DELAY_SECONDS", "60"))
)
RESOLVER_FIRST_TICK_TIMEOUT_SECONDS = max(
    1,
    int(
        os.environ.get(
            "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS",
            str(min(RESOLVER_CYCLE_TIMEOUT_SECONDS, 90)),
        )
    ),
)
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
JOB_ID = "prediction-resolver-scheduler"


def _round_robin_batch(
    subnets: list,
    cursor: int,
    batch_size: int,
) -> tuple:
    """Return a netuid-sorted batch and the next cursor position."""
    if not subnets or batch_size <= 0:
        return [], 0

    valid = [
        sn for sn in subnets
        if isinstance(sn, dict) and sn.get("netuid") is not None
    ]
    sorted_subnets = sorted(
        valid,
        key=lambda s: int(s["netuid"]) if str(s["netuid"]).isdigit() else s["netuid"],
    )
    n = len(sorted_subnets)
    if n == 0:
        return [], 0

    size = min(batch_size, n)
    cursor = cursor % n
    batch = [sorted_subnets[(cursor + i) % n] for i in range(size)]
    next_cursor = (cursor + size) % n
    return batch, next_cursor


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


class _CycleTiming:
    """Thread-safe bounded timing evidence for one resolver cycle."""

    def __init__(self, abandoned_live: int = 0):
        self._started = time.perf_counter()
        self._lock = threading.Lock()
        self._stage_timing_ms: Dict[str, float] = {}
        self._active_stage: Optional[str] = None
        self._hydrate_ms_total = 0.0
        self._hydrate_ms_max = 0.0
        self._hydration_count = 0
        self._tmc_lock_wait_ms = 0.0
        self._abandoned_live = abandoned_live
        self._abandoned = False

    @contextmanager
    def stage(
        self, name: str, on_finally: Callable[[], None]
    ) -> Iterator[None]:
        started = time.perf_counter()
        with self._lock:
            self._active_stage = name
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            with self._lock:
                self._stage_timing_ms[f"{name}_ms"] = round(elapsed_ms, 1)
                self._active_stage = None
            on_finally()

    def record_hydration(self, duration_ms: float) -> None:
        with self._lock:
            self._hydrate_ms_total += duration_ms
            self._hydrate_ms_max = max(self._hydrate_ms_max, duration_ms)
            self._hydration_count += 1

    def record_tmc_lock_wait(self, duration_ms: float) -> None:
        with self._lock:
            self._tmc_lock_wait_ms += duration_ms

    def mark_abandoned(self) -> None:
        with self._lock:
            self._abandoned = True

    def set_abandoned_live(self, count: int) -> None:
        with self._lock:
            self._abandoned_live = count

    def is_abandoned(self) -> bool:
        with self._lock:
            return self._abandoned

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            stage_timing_ms = dict(self._stage_timing_ms)
            stage_timing_ms.update(
                {
                    "hydrate_ms_total": round(self._hydrate_ms_total, 1),
                    "hydrate_ms_max": round(self._hydrate_ms_max, 1),
                    "hydration_count": self._hydration_count,
                    "tmc_lock_wait_ms": round(self._tmc_lock_wait_ms, 1),
                }
            )
            active_stage = self._active_stage
            abandoned_live = self._abandoned_live
        stage_timing_ms["total_cycle_ms"] = round(
            (time.perf_counter() - self._started) * 1000, 1
        )
        return {
            "stage_timing_ms": stage_timing_ms,
            "active_stage": active_stage,
            "abandoned_live": abandoned_live,
        }


_cycle_timing: ContextVar[Optional[_CycleTiming]] = ContextVar(
    "resolver_cycle_timing", default=None
)


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

        self._lock = threading.Lock()
        self._cycle_lock = threading.Lock()
        self._cycle_generation = 0
        self._abandoned_live = 0
        # Control-flow flag only (start/stop); health reporting goes through
        # the tracker below, never through stored booleans (spec §2).
        self._active = False
        self.liveness = LivenessTracker(
            name="prediction_resolver",
            interval_seconds=max(60, int(refresh_minutes) * 60),
            staleness_factor=2,
            persist=True,
        )
        self._backoff_minutes = refresh_minutes
        self._consecutive_failures = 0
        self._last_run_error: Optional[str] = None
        self._next_run_at: Optional[float] = None
        self._last_resolved = 0
        self._last_expired = 0
        self._last_pending = 0
        self._lifecycle = "stopped"
        self._started_at: Optional[str] = None
        self._first_tick_scheduled_at: Optional[str] = None
        self._first_tick_at: Optional[str] = None
        self._first_tick_ok: Optional[bool] = None
        self._lifecycle_error: Optional[str] = None
        self._first_tick_pending = False

    def start(self, immediate: bool = False) -> Dict[str, Any]:
        """Start the scheduler. Idempotent."""
        with self._lock:
            if self._active:
                return {"started": False, "reason": "already running"}
            self._active = True
            self._backoff_minutes = self.refresh_minutes
            self._consecutive_failures = 0
            self._lifecycle = "starting"
            self._started_at = _now_iso()
            self._first_tick_at = None
            self._first_tick_ok = None
            self._lifecycle_error = None
            self._first_tick_pending = True
            delay = 0 if immediate else RESOLVER_FIRST_TICK_DELAY_SECONDS
            self._first_tick_scheduled_at = _now_iso() if delay == 0 else datetime.fromtimestamp(
                time.time() + delay, timezone.utc
            ).isoformat()
            self._persist_lifecycle_state()
            logger.info(
                "resolver lifecycle event=start immediate=%s first_tick_at=%s",
                immediate,
                self._first_tick_scheduled_at,
            )

        if immediate:
            # Run the first tick in a background thread so callers are not
            # blocked while prices are fetched and predictions are graded.
            threading.Thread(target=self._tick, daemon=True).start()
        else:
            # First tick happens soon after boot so a backlog of pending
            # predictions is cleared quickly; normal cadence resumes after.
            self._schedule_next_seconds(RESOLVER_FIRST_TICK_DELAY_SECONDS)
        logger.info(
            "resolver lifecycle event=scheduled first_tick_at=%s",
            self._first_tick_scheduled_at,
        )

        return {
            "started": True,
            "refresh_minutes": self.refresh_minutes,
            "next_run_at": self._next_run_at,
            "lifecycle": self._lifecycle,
        }

    def stop(self) -> Dict[str, Any]:
        """Stop the scheduler and cancel any pending tick."""
        with self._lock:
            self._active = False
            self._next_run_at = None
            self._lifecycle = "stopped"
            self._first_tick_pending = False
            self._persist_lifecycle_state()
        cancel_job(JOB_ID)
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
                "running": self._active,
                "refresh_minutes": self.refresh_minutes,
                "backoff_minutes": self._backoff_minutes,
                "consecutive_failures": self._consecutive_failures,
                "last_run_at": self.liveness.snapshot().get("last_event_at"),
                "last_run_ok": self._liveness_ok(),
                "last_run_error": self._last_run_error,
                "next_run_at": self._next_run_at,
                "last_resolved": self._last_resolved,
                "last_expired": self._last_expired,
                "last_pending": self._last_pending,
                "lifecycle": self._lifecycle,
                "started_at": self._started_at,
                "first_tick_scheduled_at": self._first_tick_scheduled_at,
                "first_tick_at": self._first_tick_at,
                "first_tick_ok": self._first_tick_ok,
                "lifecycle_error": self._lifecycle_error,
            }

    def run_once(self) -> Dict[str, Any]:
        """Execute a single resolution cycle synchronously."""
        return self._tick()

    def _liveness_ok(self) -> bool:
        """True iff the age-derived tracker status is currently ok."""
        return self.liveness.snapshot()["status"] == "ok"

    def should_refresh(self) -> bool:
        if not self._active:
            return False
        return True

    def check_and_run(self) -> Dict[str, Any]:
        """Run a cycle if the scheduler is running (request-triggered refresh)."""
        if self.should_refresh():
            return self._tick()
        return {
            "skipped": True,
            "reason": "not running",
            "status": self.liveness.snapshot()["status"],
            "last_run_at": self.liveness.snapshot().get("last_event_at"),
        }

    def _schedule_next(self, minutes: int) -> None:
        self._schedule_next_seconds(minutes * 60)

    def _schedule_next_seconds(self, seconds: float) -> None:
        with self._lock:
            if not self._active:
                return
            self._next_run_at = time.time() + seconds
            if self._first_tick_pending:
                self._lifecycle = "scheduled"
        schedule_in_seconds(JOB_ID, self._tick, seconds)

    def _tick(self) -> Dict[str, Any]:
        """Run one resolution cycle and reschedule."""
        from internal.heavy_job_gate import heavy_job_slot

        tick_started = time.perf_counter()
        with self._lock:
            first_tick = self._first_tick_pending
            if first_tick:
                self._lifecycle = "ticking"
            else:
                self._lifecycle = "running"
        logger.info("resolver lifecycle event=tick_start first=%s", first_tick)
        with heavy_job_slot("prediction_resolver") as acquired:
            if not acquired:
                skipped = {
                    "run_at": _now_iso(),
                    "skipped": "heavy_job_busy",
                    "resolved_now": 0,
                    "expired_now": 0,
                    "pending": 0,
                }
                self._persist_cycle_summary(skipped)
                # Skips are recorded honestly; they never produce ok (spec §2).
                self.liveness.record_skip(reason="heavy_job_busy")
                with self._lock:
                    self._last_run_error = None
                    self._mark_first_tick(skipped)
                logger.info(
                    "resolver lifecycle event=skip first=%s duration_ms=%.1f reason=heavy_job_busy",
                    first_tick,
                    (time.perf_counter() - tick_started) * 1000,
                )
                if self._active:
                    # Retry sooner so pending_past_grace doesn't rot behind long snapshots.
                    self._schedule_next(min(2, max(1, self.refresh_minutes)))
                return skipped
            result = self._run_refresh_cycle_with_timeout()

        if result.get("ok"):
            self.liveness.record_success(
                evidence={
                    "resolved_now": result.get("resolved_now", 0),
                    "expired_now": result.get("expired_now", 0),
                    "pending": result.get("pending", 0),
                }
            )
        elif result.get("error"):
            self.liveness.record_failure(error=str(result.get("error")))
        else:
            self.liveness.record_skip(reason=str(result.get("skipped") or "cycle_skipped"))

        with self._lock:
            self._last_run_error = result.get("error")
            self._last_resolved = result.get("resolved_now", 0)
            self._last_expired = result.get("expired_now", 0)
            self._last_pending = result.get("pending", 0)
            self._lifecycle = "running" if result.get("ok") else "degraded"
            self._lifecycle_error = result.get("error")
            if result.get("ok"):
                self._consecutive_failures = 0
                self._backoff_minutes = self.refresh_minutes
            else:
                self._consecutive_failures += 1
                self._backoff_minutes = min(
                    self.refresh_minutes * (2 ** self._consecutive_failures),
                    self.max_backoff_minutes,
                )
            next_interval = self._backoff_minutes
            if "cycle_timeout" in str(result.get("error") or ""):
                # ponytail: hung cycle abandoned — retry soon while last success still fresh
                next_interval = min(2, max(1, self.refresh_minutes))
            self._mark_first_tick(result)

        duration_ms = (time.perf_counter() - tick_started) * 1000
        if result.get("error") and "timeout" in str(result.get("error")).lower():
            logger.warning(
                "resolver lifecycle event=timeout first=%s duration_ms=%.1f error=%s",
                first_tick,
                duration_ms,
                result.get("error"),
            )
        elif result.get("skipped"):
            logger.info(
                "resolver lifecycle event=skip first=%s duration_ms=%.1f reason=%s",
                first_tick,
                duration_ms,
                result.get("skipped"),
            )
        elif result.get("ok"):
            logger.info(
                "resolver lifecycle event=success first=%s duration_ms=%.1f",
                first_tick,
                duration_ms,
            )
        else:
            logger.warning(
                "resolver lifecycle event=failure first=%s duration_ms=%.1f error=%s",
                first_tick,
                duration_ms,
                result.get("error"),
            )
        if self._active:
            self._schedule_next(next_interval)
        return result

    def _mark_first_tick(self, result: Dict[str, Any]) -> None:
        if self._first_tick_at is not None:
            return
        self._first_tick_pending = False
        self._first_tick_at = result.get("run_at") or _now_iso()
        self._first_tick_ok = bool(result.get("ok"))
        self._lifecycle = "running" if result.get("ok") else "degraded"
        self._lifecycle_error = result.get("error")
        self._persist_lifecycle_state()

    def _persist_lifecycle_state(self) -> None:
        state = {
            "lifecycle": self._lifecycle,
            "started_at": self._started_at,
            "first_tick_scheduled_at": self._first_tick_scheduled_at,
            "first_tick_at": self._first_tick_at,
            "first_tick_ok": self._first_tick_ok,
            "lifecycle_error": self._lifecycle_error,
        }
        def _mutator(data: Dict[str, Any]) -> None:
            data.setdefault("prediction_resolver_scheduler", {}).update(state)
        try:
            write_soul_map(_mutator, self.soul_map_path)
        except Exception:
            pass

    def _abandon_inflight_cycle(self) -> None:
        """Release wedge after cycle timeout; orphan thread must not double-release."""
        self._cycle_generation += 1
        try:
            self._cycle_lock.release()
        except RuntimeError:
            pass

    def _get_abandoned_live(self) -> int:
        """Return the count of cycles abandoned by the timeout boundary."""
        with self._lock:
            return self._abandoned_live

    def _run_refresh_cycle_with_timeout(self) -> Dict[str, Any]:
        abandoned_live = self._get_abandoned_live()
        logger.info("resolver abandoned_live=%d", abandoned_live)
        if not self._cycle_lock.acquire(blocking=False):
            result = {
                "run_at": _now_iso(),
                "resolved_now": 0,
                "expired_now": 0,
                "pending": 0,
                "skipped": "cycle_in_flight",
                "abandoned_live": abandoned_live,
            }
            self._persist_cycle_summary(result)
            return result

        timeout = (
            RESOLVER_FIRST_TICK_TIMEOUT_SECONDS
            if self._first_tick_pending
            else RESOLVER_CYCLE_TIMEOUT_SECONDS
        )
        if timeout <= 0:
            timing = _CycleTiming(abandoned_live)
            token = _cycle_timing.set(timing)
            try:
                return self._run_refresh_cycle()
            finally:
                _cycle_timing.reset(token)
                self._cycle_lock.release()

        self._cycle_generation += 1
        gen = self._cycle_generation
        pool = ThreadPoolExecutor(max_workers=1)
        timing = _CycleTiming(abandoned_live)

        def _run_cycle() -> Dict[str, Any]:
            token = _cycle_timing.set(timing)
            try:
                if gen != self._cycle_generation:
                    return {
                        "ok": False,
                        "run_at": _now_iso(),
                        "resolved_now": 0,
                        "expired_now": 0,
                        "pending": 0,
                        "skipped": "cycle_abandoned",
                    }
                return self._run_refresh_cycle()
            finally:
                _cycle_timing.reset(token)
                if gen == self._cycle_generation:
                    self._cycle_lock.release()

        submitted = False
        try:
            fut = pool.submit(_run_cycle)
            submitted = True
            try:
                return fut.result(timeout=timeout)
            except FuturesTimeoutError:
                self._abandon_inflight_cycle()
                with self._lock:
                    self._abandoned_live += 1
                    abandoned_live = self._abandoned_live
                timing.set_abandoned_live(abandoned_live)
                timing.mark_abandoned()
                result = {
                    "ok": False,
                    "run_at": _now_iso(),
                    "resolved_now": 0,
                    "expired_now": 0,
                    "pending": 0,
                    "error": f"cycle_timeout_{timeout}s",
                    "abandoned_live": abandoned_live,
                }
                self._apply_cycle_timing(result, timing)
                self._persist_cycle_summary(result)
                return result
        except BaseException:
            if not submitted:
                self._cycle_lock.release()
            raise
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _apply_cycle_timing(
        self, result: Dict[str, Any], timing: _CycleTiming
    ) -> None:
        evidence = timing.snapshot()
        result["stage_timing_ms"] = evidence["stage_timing_ms"]
        result["active_stage"] = evidence["active_stage"]
        result["abandoned_live"] = evidence["abandoned_live"]

    def _resolve_with_timing(
        self, subnets: Any, timing: _CycleTiming
    ) -> Dict[str, Any]:
        from internal.council import price_reference

        tmc_context = nullcontext()
        try:
            from internal.indicators import tmc_singleflight

            tmc_context = tmc_singleflight.lock_wait_timing(
                timing.record_tmc_lock_wait
            )
        except Exception:
            pass
        with price_reference.hydration_timing(timing.record_hydration):
            with tmc_context:
                return resolver.resolve_due_predictions(subnets)

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
        timing = _cycle_timing.get() or _CycleTiming()

        def persist_partial() -> None:
            if timing.is_abandoned():
                return
            self._apply_cycle_timing(result, timing)
            self._persist_cycle_summary(result)

        try:
            with timing.stage("ledger_heal", persist_partial):
                try:
                    from internal.learning.ledger_heal import heal_daily_pick_ledger

                    heal_daily_pick_ledger(dry_run=False)
                except Exception as heal_exc:
                    import logging
                    logging.getLogger(__name__).warning(
                        "ledger heal in resolver tick failed: %s", heal_exc
                    )

            with timing.stage("subnet_provider", persist_partial):
                subnets = self._subnet_provider() or []

            with timing.stage("soul_map_load", persist_partial):
                soul_data = _load_json(self.soul_map_path)
            sched_state = soul_data.get("prediction_resolver_scheduler", {})
            if not isinstance(sched_state, dict):
                sched_state = {}
            cursor = int(sched_state.get("round_robin_cursor", 0) or 0)
            batch, next_cursor = _round_robin_batch(
                subnets, cursor, RESOLVER_BATCH_SIZE
            )
            result["batch_size"] = len(batch)
            result["round_robin_cursor"] = next_cursor

            # 1. Grade predictions whose horizon has elapsed against the live
            #    price feed. This also nudges expert weights (learning loop).
            #    Pass the full subnet list so fetch_prices covers every pending
            #    netuid; round-robin batch above is telemetry/cursor only.
            #    ``resolve_due_predictions`` itself retires predictions that are
            #    past due with no price as ``expired`` (correct=None), so we
            #    count those here too.
            with timing.stage("resolve_due", persist_partial):
                resolved = self._resolve_with_timing(subnets, timing)
            result["resolved_now"] = len(resolved.get("resolved_now", []))
            expired_count = len(resolved.get("expired_now", []))

            # 2. Safety net: retire any predictions that are past due with no
            #    resolvable price so the registry never fills with ungradeable
            #    ``pending`` rows (delisted subnet / feed outage / corrupt row).
            #    Most are already retired in step 1; this catches stragglers
            #    (e.g. corrupt records that step 1 skipped).
            with timing.stage("expire_stale", persist_partial):
                expired = resolver.expire_stale_predictions()
            expired_count += len(expired.get("expired_now", []))
            result["expired_now"] = expired_count
            result["pending"] = expired.get("stats", {}).get("pending", 0)
            result["watchdog"] = resolved.get("watchdog") or expired.get("watchdog")

            result["ok"] = True
            result["stats"] = expired.get("stats", resolved.get("stats", {}))

            # N3: optional env-gated auto-retrain after resolver (non-blocking).
            with timing.stage("auto_retrain", persist_partial):
                try:
                    from internal.calibration.scheduler import maybe_trigger_auto_retrain

                    result["auto_retrain"] = maybe_trigger_auto_retrain(
                        resolved_now=result.get("resolved_now", 0)
                    )
                except Exception as exc:
                    result["auto_retrain"] = {"triggered": False, "error": str(exc)}
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            if not timing.is_abandoned():
                self._apply_cycle_timing(result, timing)
                self._persist_cycle_summary(result)
        return result

    def _persist_cycle_summary(self, result: Dict[str, Any]) -> None:
        summary = {
            "run_at": result["run_at"],
            "ok": result.get("ok", False),
            "resolved_now": result.get("resolved_now", 0),
            "expired_now": result.get("expired_now", 0),
            "pending": result.get("pending", 0),
            "error": result.get("error"),
            "skipped": result.get("skipped"),
            "watchdog": result.get("watchdog"),
            "batch_size": result.get("batch_size", 0),
            "round_robin_cursor": result.get("round_robin_cursor"),
            "stage_timing_ms": dict(result.get("stage_timing_ms") or {}),
            "active_stage": result.get("active_stage"),
            "abandoned_live": result.get("abandoned_live", 0),
            "lifecycle": self._lifecycle,
        }
        def _mutator(data: Dict[str, Any]) -> None:
            sched = data.setdefault("prediction_resolver_scheduler", {})
            sched["last_cycle"] = summary
            sched["lifecycle"] = self._lifecycle
            sched["lifecycle_error"] = self._lifecycle_error
            if self._first_tick_at is not None:
                sched["first_tick_at"] = self._first_tick_at
            if result.get("round_robin_cursor") is not None:
                sched["round_robin_cursor"] = result["round_robin_cursor"]

        try:
            write_soul_map(_mutator, self.soul_map_path)
        except Exception:
            pass


def _default_subnets() -> Any:
    """Return cached worker subnet rows for resolver ticks.

    Imported lazily so this module never creates a circular import with
    ``server`` (which imports the scheduler on startup).
    """
    try:
        from internal.live_subnets import get_live_subnets

        # ``get_live_subnets`` reads the worker-owned JSON cache and falls back
        # to the committed registry.  Resolver ticks must not enter the
        # network-backed council feed or its TaoMarketCap overlay.
        return get_live_subnets()
    except Exception:
        try:
            from internal.subnets.feed import registry_subnet_rows

            return registry_subnet_rows()
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
    try:
        from internal.pump.scheduler import stop_pump_ladder_scheduler

        stop_pump_ladder_scheduler()
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


def _stopped_liveness_ok() -> Optional[bool]:
    """Registry-derived ok for the stopped singleton (honest persisted view)."""
    try:
        from internal.liveness import get_tracker

        t = get_tracker("prediction_resolver")
        if t is not None:
            return t.snapshot()["status"] == "ok"
    except Exception:
        pass
    return None


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
                "last_run_ok": _stopped_liveness_ok(),
                "last_run_error": None,
                "next_run_at": None,
                "last_resolved": 0,
                "last_expired": 0,
                "last_pending": 0,
                "lifecycle": "stopped",
                "started_at": None,
                "first_tick_scheduled_at": None,
                "first_tick_at": None,
                "first_tick_ok": None,
                "lifecycle_error": None,
            }
        return _scheduler.state()


def get_prediction_resolver_scheduler() -> Optional[PredictionResolverScheduler]:
    """Return the scheduler singleton for direct access."""
    with _scheduler_lock:
        return _scheduler


def _resolver_tick_age_seconds() -> Optional[float]:
    """Age in seconds since the resolver last persisted a cycle (None if unknown)."""
    try:
        from internal.learning.loop_health import _last_resolver_tick

        raw = _last_resolver_tick()
        tick_at = raw.get("at") if isinstance(raw, dict) else None
        if not tick_at:
            return None
        dt = datetime.fromisoformat(str(tick_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()
    except Exception:
        return None


def revive_prediction_resolver_scheduler(*, force: bool = False) -> Dict[str, Any]:
    """Best-effort in-place revive when periodic resolver ticks stop.

    Loop stall guard calls this on strike 1 for stale resolver ticks. Recycle
    whenever ``_active`` (stop + cancel JOB_ID + start), then run one synchronous
    ``run_once`` so soul_map ``last_cycle.run_at`` actually moves.
    """
    age_before = _resolver_tick_age_seconds()
    stall_after_s = max(60, RESOLVER_REFRESH_MINUTES * 2 * 60)
    if not force and age_before is not None and age_before <= stall_after_s:
        return {
            "revived": False,
            "reason": "tick_fresh",
            "recycled": False,
            "age_before": age_before,
            "age_after": age_before,
        }

    recycled = False
    global _scheduler
    with _scheduler_lock:
        sched = _scheduler
        if sched is not None and not sched._cycle_lock.acquire(blocking=False):
            return {
                "revived": False,
                "reason": "tick_in_progress",
                "recycled": False,
                "age_before": age_before,
                "age_after": _resolver_tick_age_seconds(),
            }
        if sched is not None:
            sched._cycle_lock.release()
        if sched is not None and sched._active:
            sched.stop()
            _scheduler = None
            recycled = True

    start_out = start_prediction_resolver_scheduler(immediate=False)
    tick_out: Dict[str, Any] = {"ok": False, "error": "no_scheduler"}
    with _scheduler_lock:
        sched = _scheduler
    if sched is not None:
        tick_out = sched.run_once()

    age_after = _resolver_tick_age_seconds()
    revived = bool(tick_out.get("ok") and not tick_out.get("skipped"))
    return {
        "revived": revived,
        "recycled": recycled,
        "age_before": age_before,
        "age_after": age_after,
        "start": start_out,
        "tick": tick_out,
    }
