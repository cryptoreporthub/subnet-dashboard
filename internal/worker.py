"""Fly background worker — resolver, freshness, live feed (no HTTP).

Usage: python -m internal.worker
"""

from __future__ import annotations

import logging
import signal
import sys
import threading

from internal.sentry_setup import init_sentry

init_sentry()

logger = logging.getLogger("worker")

_shutdown = threading.Event()


def _handle_signal(signum, _frame) -> None:
    logger.info("worker shutdown signal %s", signum)
    _shutdown.set()


def main() -> None:
    import os

    from internal.background_boot import start_background_workers, stop_background_workers
    from internal.worker_heartbeat import touch_heartbeat

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    from internal.run_mode import worker_heavy_feeds_enabled

    heavy = worker_heavy_feeds_enabled()

    # Resolver missing-price retry semantics (Ditto, #885): rows with
    # unavailable price data stay pending until the retry cap before expiring.
    try:
        from internal.council.resolver_semantics_patch import apply_resolver_semantics_patch

        apply_resolver_semantics_patch()
    except Exception as exc:
        logger.warning("resolver semantics patch failed to apply: %s", exc)

    start_background_workers(heavy=heavy)

    # Loop stall guard (loop-stall-guard commit d03a3789): watch the pump desk
    # snapshot age; if it stays stale across consecutive checks, revive in place
    # then exit so the supervisor restarts the worker fresh. Must stay wired in
    # alongside the scheduler self-heal below.
    try:
        from internal.loop_stall_guard import start_loop_stall_guard

        start_loop_stall_guard()
    except Exception as exc:
        logger.warning("loop stall guard failed to start: %s", exc)

    touch_heartbeat()

    def _beat() -> None:
        # Zombie-loop guard: keep touching the heartbeat ONLY while the shared
        # background scheduler is actually alive with jobs. If the scheduler is
        # dead or empty (a one-shot tick died / no re-arm), stop touching so the
        # inline-worker supervisor (fly_web_entrypoint.sh) sees a stale heartbeat
        # and restarts this process — instead of serving a "healthy" heartbeat
        # forever while the learning loop is frozen.
        import logging as _logging

        _logger = _logging.getLogger("worker")
        while not _shutdown.wait(30):
            try:
                from internal.job_scheduler import state as _sched_state

                _st = _sched_state()
                if not _st.get("running") or int(_st.get("job_count", 0) or 0) <= 0:
                    _logger.warning(
                        "background scheduler unhealthy (%s); heartbeat paused", _st
                    )
                    continue
                touch_heartbeat()
            except Exception as exc:
                _logger.warning("worker heartbeat failed: %s", exc)

    threading.Thread(target=_beat, daemon=True, name="worker-heartbeat").start()
    logger.info("background worker running (RUN_MODE=worker, heavy=%s)", heavy)
    _shutdown.wait()
    stop_background_workers()
    logger.info("background worker stopped")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
