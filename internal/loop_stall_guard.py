"""Loop stall guard — self-heal the worker when scheduler threads die silently.

Background (prod incident 2026-08-09): the Fly supervisor restarts the worker
process only when the worker heartbeat goes stale. A live process whose
internal scheduler threads have died still touches the heartbeat, so the
supervisor never restarts it and data goes stale overnight.

This guard runs inside the worker process and watches the artifact the
council score snapshot scheduler is supposed to produce —
``data/score_snapshots.json`` (probe: ``loop_health._snapshot_age_seconds``,
producer: ``internal.council.score_snapshots``):

  * every tick it logs the observed snapshot age (diagnosable),
  * on the first stale observation it attempts a safe in-place revive via
    ``revive_score_snapshot_scheduler`` (stop+restart when very stale, then
    one synchronous cycle so the guarded mtime moves),
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
from typing import Optional

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
CONSECUTIVE_CHECKS = max(1, _env_int("LOOP_STALL_GUARD_CONSECUTIVE_CHECKS", 2))
BOOT_GRACE_SECONDS = max(60, _env_int("LOOP_STALL_GUARD_BOOT_GRACE_SECONDS", 1500))
KILL_ENABLED = _env_bool("LOOP_STALL_GUARD_KILL", True)


def _snapshot_age_seconds() -> Optional[float]:
    """Age in seconds of score_snapshots.json (None if unknown)."""
    try:
        from internal.learning.loop_health import _snapshot_age_seconds as _age

        return _age()
    except Exception as exc:
        logger.debug("loop stall guard: snapshot age probe failed: %s", exc)
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
        logger.debug("loop stall guard: resolver tick probe failed: %s", exc)
        return None


def _worker_mode() -> bool:
    try:
        from internal.run_mode import is_worker_mode

        return is_worker_mode()
    except Exception:
        return True  # assume worker context; guard is otherwise inert


def _try_revive() -> None:
    try:
        from internal.council.score_snapshots import revive_score_snapshot_scheduler

        result = revive_score_snapshot_scheduler()
        logger.warning("loop stall guard: in-place revive attempt -> %s", result)
    except Exception as exc:
        logger.warning("loop stall guard: revive attempt failed: %s", exc)


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

    logger.info(
        "loop stall guard started (interval=%ss, max_snapshot_age=%ss, consecutive=%s, kill=%s)",
        INTERVAL_SECONDS,
        MAX_SNAPSHOT_AGE_SECONDS,
        CONSECUTIVE_CHECKS,
        KILL_ENABLED,
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

        if age is None:
            consecutive_stale = 0
            logger.info("loop stall guard: no snapshot age signal (boot/feature-off), resetting")
            continue

        if age <= MAX_SNAPSHOT_AGE_SECONDS:
            consecutive_stale = 0
            logger.info("loop stall guard: snapshot fresh (age=%ss)", int(age))
            continue

        consecutive_stale += 1
        logger.warning(
            "loop stall guard: snapshot STALE (age=%ss, threshold=%ss, strike=%s/%s)",
            int(age),
            MAX_SNAPSHOT_AGE_SECONDS,
            consecutive_stale,
            CONSECUTIVE_CHECKS,
        )

        if consecutive_stale == 1 and not revived:
            revived = True
            _try_revive()

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
