"""Loop stall guard — self-heal the worker when scheduler threads die silently.

Background (prod incident 2026-08-09): the Fly supervisor restarts the worker
process only when the worker heartbeat goes stale. A live process whose
internal scheduler threads have died still touches the heartbeat, so the
supervisor never restarts it and data goes stale overnight.

This guard runs inside the worker process and watches the score snapshot
producer through its cycle receipt, or the served snapshot while no receipt
exists (probe: ``_snapshot_age_seconds``, producer:
``internal.council.score_snapshots``):

  * every tick it logs the observed snapshot age (diagnosable),
  * on the first stale observation it attempts a safe in-place revive via
    ``revive_score_snapshot_scheduler`` (recycle whenever the scheduler claims
    running, then one synchronous cycle so the guarded mtime moves),
  * if the snapshot stays stale for LOOP_STALL_GUARD_CONSECUTIVE_CHECKS
    consecutive ticks it logs CRITICAL and exits(1) so the supervisor
    restarts the worker fresh (which re-runs background_boot and revives
    every scheduler).

All knobs are env-gated so behavior can be tuned or disabled from Fly
secrets without a code change.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_GUARD_NAME = "loop-stall-guard"


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


ENABLED = _env_bool("LOOP_STALL_GUARD_ENABLED", True)
INTERVAL_SECONDS = max(30, _env_int("LOOP_STALL_GUARD_INTERVAL_SECONDS", 240))
MAX_SNAPSHOT_AGE_SECONDS = max(
    300, _env_int("LOOP_STALL_GUARD_MAX_SNAPSHOT_AGE_SECONDS", 5400)
)
MAX_RESOLVER_AGE_SECONDS = max(
    1800, _env_int("LOOP_STALL_GUARD_MAX_RESOLVER_AGE_SECONDS", 21600)
)
RESOLVER_REVIVE_AFTER_SECONDS = max(
    900,
    _env_int("LOOP_STALL_GUARD_RESOLVER_REVIVE_SECONDS", 2400),
)
# ponytail: P4b soak4 — third strike before kill; upgrade path = env CONSECUTIVE_CHECKS=2
CONSECUTIVE_CHECKS = max(1, _env_int("LOOP_STALL_GUARD_CONSECUTIVE_CHECKS", 3))
# ponytail: loop_health snapshot boot grace defaults 900s; guard waits 1500s — intentional dual, no knob change
BOOT_GRACE_SECONDS = max(60, _env_int("LOOP_STALL_GUARD_BOOT_GRACE_SECONDS", 1500))
KILL_ENABLED = _env_bool("LOOP_STALL_GUARD_KILL", True)
# A scoring tick that is running and still advancing is not a wedge even when the last
# receipt is old. Judge it by progress on the monotonic clock. The no-progress deadline is
# the scheduler's own stuck threshold (SCORE_SNAPSHOT_STUCK_SECONDS), read from the scheduler
# so the two can never disagree; LOOP_STALL_GUARD_TICK_PROGRESS_SECONDS may only raise it.
# The cap is absolute: a tick still running tick_max_seconds() after the guard FIRST saw it is
# hung too, even if it keeps advancing or resumed after a stall. It is counted from first sight,
# never from the last progress (that would just be the no-progress deadline again), so a tick
# that stalled and resumed does NOT get a fresh runway.
TICK_PROGRESS_OVERRIDE_SECONDS = _env_int("LOOP_STALL_GUARD_TICK_PROGRESS_SECONDS", 0)
TICK_MAX_BASE_SECONDS = _env_int("LOOP_STALL_GUARD_TICK_MAX_SECONDS", 3600)
_override_clamp_logged = False


def tick_progress_seconds() -> int:
    """No-progress deadline: never below the scheduler's stuck threshold or its write timeout."""
    global _override_clamp_logged
    try:
        from internal.council.score_snapshots import score_snapshot_stuck_seconds

        threshold = int(score_snapshot_stuck_seconds())
    except Exception as exc:
        logger.warning("loop stall guard: scheduler stuck threshold unreadable (%s); using 900s", exc)
        threshold = 900
    threshold = max(60, threshold)
    try:
        from internal.council.score_snapshots import SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS

        write_timeout = int(SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS)
    except Exception:
        write_timeout = 0
    if write_timeout > 0:
        # The progress token is constant while the write phase waits (up to the write timeout),
        # so the deadline must outlast a healthy write. The default (600s) is below 900s: no change.
        threshold = max(threshold, write_timeout + 60)
    if TICK_PROGRESS_OVERRIDE_SECONDS and TICK_PROGRESS_OVERRIDE_SECONDS < threshold:
        if not _override_clamp_logged:
            _override_clamp_logged = True
            logger.warning(
                "loop stall guard: LOOP_STALL_GUARD_TICK_PROGRESS_SECONDS=%s is below the scheduler "
                "stuck threshold (%ss); using the scheduler threshold",
                TICK_PROGRESS_OVERRIDE_SECONDS,
                threshold,
            )
        return threshold
    return max(threshold, TICK_PROGRESS_OVERRIDE_SECONDS)


def tick_max_seconds() -> int:
    """Absolute cap on one running tick, counted from when the guard first saw it.

    Progress does not extend it. It is only kept at least twice the no-progress deadline,
    so a tick that is merely slow (never stalled) is never cut off by the cap alone.
    """
    return max(TICK_MAX_BASE_SECONDS, 2 * tick_progress_seconds())


def _now_mono() -> float:
    return time.monotonic()


# A receipt or snapshot dated further ahead than this is not evidence of life
# (clock step or a corrupt file); small skew is tolerated and reads as age 0.
FUTURE_TIMESTAMP_TOLERANCE_SECONDS = 300


def _evidence_age(signed_age: Optional[float]) -> Optional[float]:
    """Age of a liveness witness; a future-dated one is stale, never fresh."""
    if signed_age is None:
        return None
    if signed_age < -FUTURE_TIMESTAMP_TOLERANCE_SECONDS:
        logger.warning(
            "loop stall guard: snapshot evidence is dated %.0fs in the future; treating as stale",
            -signed_age,
        )
        return float(MAX_SNAPSHOT_AGE_SECONDS + 1)
    return max(0.0, signed_age)


def _snapshot_age_seconds() -> Optional[float]:
    """Producer liveness for the score-snapshot owner; None (idle) everywhere else.

    * Not the producer (hop, WORKER_HEAVY=off, web) or the freeze lever is off:
      None. Those processes never write a receipt, so any age would restart-loop.
    * Owner with a cycle receipt: receipt age (published, refused or gated).
    * Owner with no receipt: only a volume snapshot counts as evidence. Its age
      is returned as is, and an unknown age is unknown (None: the guard resets
      instead of striking, because readers still have a snapshot). The committed
      seed never counts, young or not: it is a static artifact, so it proves
      nothing about the producer. No receipt and no volume snapshot means the
      producer has not completed a cycle; that is stale on the first check (the
      guard's boot grace covers a normal startup).
    * A receipt or volume snapshot dated more than FUTURE_TIMESTAMP_TOLERANCE_SECONDS
      ahead of now is stale: a clock step or corrupt file cannot prove the producer
      is alive, and a wedged producer must not hide behind it. The revive rewrites
      the receipt, so a live producer self-heals.
    """
    try:
        from internal.council import score_snapshots as snaps
        from internal.council.score_snapshots import (
            _enabled,
            producer_cycle_age_seconds,
            read_served_snapshot,
        )
        from internal.run_mode import score_snapshot_producer_enabled

        if not _enabled() or not score_snapshot_producer_enabled():
            return None
        cycle_age = producer_cycle_age_seconds(signed=True)
        if cycle_age is not None:
            return _evidence_age(cycle_age)
        served = read_served_snapshot()
        if served.servable and served.origin == "volume":
            if served.age_seconds is None:
                return None
            # served.age_seconds is clamped at 0; re-read it signed to see a future date.
            return _evidence_age(
                snaps._snapshot_age_for_path(
                    snaps.SCORE_SNAPSHOTS_PATH, served.snapshot, signed=True
                )
            )
        return float(MAX_SNAPSHOT_AGE_SECONDS + 1)
    except Exception as exc:
        logger.warning("loop stall guard: snapshot age probe failed: %s", exc)
        return None


def _resolver_tick_age_seconds() -> Optional[float]:
    """Age in seconds since the resolver last ticked (None if unknown)."""
    try:
        from datetime import datetime, timezone

        from internal.learning.loop_health import _last_resolver_tick

        raw = _last_resolver_tick()
        if not raw:
            return None
        # _last_resolver_tick returns a dict with key "at" for the ISO timestamp.
        tick_at = raw.get("at") if isinstance(raw, dict) else None
        if not tick_at:
            return None
        dt = datetime.fromisoformat(str(tick_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()
    except Exception as exc:
        logger.warning("loop stall guard: resolver tick probe failed: %s", exc)
        return None


def _worker_mode() -> bool:
    try:
        from internal.run_mode import is_worker_mode

        return is_worker_mode()
    except Exception:
        return True  # assume worker context; guard is otherwise inert


def _try_revive() -> Optional[Dict[str, Any]]:
    try:
        from internal.council.score_snapshots import revive_score_snapshot_scheduler

        result = revive_score_snapshot_scheduler()
        logger.warning("loop stall guard: in-place revive attempt -> %s", result)
        return result
    except Exception as exc:
        logger.warning("loop stall guard: revive attempt failed: %s", exc)
        return None


def _tick_progress() -> Optional[Dict[str, Any]]:
    """Progress marker of a running scoring tick, or None (no tick, or unreadable)."""
    try:
        from internal.council.score_snapshots import producer_tick_progress

        return producer_tick_progress()
    except Exception as exc:
        logger.warning("loop stall guard: tick progress probe failed: %s", exc)
        return None


class _TickWatch:
    """What the guard has seen of one running tick, on the monotonic clock.

    ``first_seen`` never moves (the absolute cap counts from it); ``last_progress``
    moves every time the progress token changes (the no-progress deadline counts from it).
    """

    def __init__(self, token: Any, now: float) -> None:
        self.token = token
        self.first_seen = now
        self.last_progress = now

    def observe(self, token: Any, now: float) -> None:
        if token != self.token:
            self.token = token
            self.last_progress = now

    def hung(self, now: float) -> bool:
        return (
            now - self.last_progress > tick_progress_seconds()
            or now - self.first_seen > tick_max_seconds()
        )


def _try_revive_resolver() -> None:
    try:
        from internal.council.resolver_scheduler import revive_prediction_resolver_scheduler

        result = revive_prediction_resolver_scheduler()
        logger.warning("loop stall guard: resolver revive attempt -> %s", result)
    except Exception as exc:
        logger.warning("loop stall guard: resolver revive failed: %s", exc)


def _guard_loop() -> None:
    if not ENABLED:
        logger.info("loop stall guard: disabled (LOOP_STALL_GUARD_ENABLED=0)")
        return
    if not _worker_mode():
        logger.info("loop stall guard: not worker mode, staying idle")
        return

    started = time.monotonic()
    consecutive_stale = 0
    revived = False
    resolver_revived = False
    watch: Optional[_TickWatch] = None
    withdrawn = False  # one premature strike per stale episode may be withdrawn

    logger.info(
        "loop stall guard started (interval=%ss, max_snapshot_age=%ss, resolver_revive_after=%ss, "
        "consecutive=%s, kill=%s, tick_progress=%ss, tick_max=%ss)",
        INTERVAL_SECONDS,
        MAX_SNAPSHOT_AGE_SECONDS,
        RESOLVER_REVIVE_AFTER_SECONDS,
        CONSECUTIVE_CHECKS,
        KILL_ENABLED,
        tick_progress_seconds(),
        tick_max_seconds(),
    )
    while True:
        time.sleep(INTERVAL_SECONDS)
        if time.monotonic() - started < BOOT_GRACE_SECONDS:
            continue

        age = _snapshot_age_seconds()
        resolver_age = _resolver_tick_age_seconds()

        if resolver_age is not None and resolver_age > MAX_RESOLVER_AGE_SECONDS:
            logger.warning(
                "loop stall guard: resolver tick stale (age=%ss, threshold=%ss) — warn only",
                int(resolver_age),
                MAX_RESOLVER_AGE_SECONDS,
            )

        if (
            resolver_age is not None
            and resolver_age > RESOLVER_REVIVE_AFTER_SECONDS
            and not resolver_revived
        ):
            resolver_revived = True
            _try_revive_resolver()

        if age is None:
            consecutive_stale = 0
            watch = None
            withdrawn = False
            logger.info("loop stall guard: not the snapshot producer or scheduler frozen, resetting")
            continue

        if age <= MAX_SNAPSHOT_AGE_SECONDS:
            consecutive_stale = 0
            watch = None
            withdrawn = False
            logger.info("loop stall guard: snapshot fresh (age=%ss)", int(age))
            continue

        # Old output, but a running scoring tick that keeps advancing is working, not wedged.
        tick = _tick_progress()
        if tick is None:
            watch = None
        else:
            now = _now_mono()
            if watch is None:
                watch = _TickWatch(tick.get("token"), now)
            else:
                watch.observe(tick.get("token"), now)
            if not watch.hung(now):
                consecutive_stale = 0
                logger.info(
                    "loop stall guard: snapshot old (age=%ss) but a scoring tick is running and "
                    "advancing (last progress %ss ago); not striking",
                    int(age),
                    int(now - watch.last_progress),
                )
                continue
            logger.warning(
                "loop stall guard: scoring tick has not advanced for %ss (running %ss); counting as hung",
                int(now - watch.last_progress),
                int(now - watch.first_seen),
            )

        consecutive_stale += 1
        logger.warning(
            "loop stall guard: snapshot STALE (age=%ss, threshold=%ss, strike=%s/%s)",
            int(age),
            MAX_SNAPSHOT_AGE_SECONDS,
            consecutive_stale,
            CONSECUTIVE_CHECKS,
        )

        if not revived:
            result = _try_revive()
            if isinstance(result, dict) and result.get("reason") == "tick_in_progress":
                # Not a revive: a tick is running and revive cannot stop it.
                if watch is None and not withdrawn:
                    # A tick started after our check, so this strike was premature:
                    # start judging it by progress on the next check.
                    withdrawn = True
                    consecutive_stale = 0
                    logger.info(
                        "loop stall guard: revive found a tick that started after the check; "
                        "strike withdrawn"
                    )
                    continue
                # A hung tick (past its progress deadline): the strike stands; revive may retry.
            elif isinstance(result, dict) and result.get("reason") == "not_owner":
                # Not the producer: nothing here can refresh the file, so this is idle, not wedged.
                consecutive_stale = 0
                logger.info("loop stall guard: revive says not_owner; staying idle")
                continue
            else:
                revived = True

        if consecutive_stale >= CONSECUTIVE_CHECKS:
            logger.critical(
                "loop stall guard: snapshot stale for %s checks (age=%ss) — worker schedulers "
                "appear wedged; exiting for supervisor restart (kill=%s)",
                consecutive_stale,
                int(age),
                KILL_ENABLED,
            )
            if KILL_ENABLED:
                try:
                    import sys

                    sys.stdout.flush()
                    sys.stderr.flush()
                except Exception:
                    pass
                os._exit(1)
            else:
                logger.warning("loop stall guard: kill disabled, would have exited")


def start_loop_stall_guard() -> None:
    """Start the guard daemon. Safe to call multiple times (idempotent)."""
    for t in threading.enumerate():
        if t.name == _GUARD_NAME:
            return
    threading.Thread(target=_guard_loop, daemon=True, name=_GUARD_NAME).start()
    logger.info("loop stall guard daemon spawned")
