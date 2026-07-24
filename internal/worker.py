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

    heavy_flag = os.environ.get("WORKER_HEAVY", "essential").strip().lower()
    heavy = heavy_flag in ("1", "true", "yes", "on", "full")
    start_background_workers(heavy=heavy)
    touch_heartbeat()

    def _beat() -> None:
        while not _shutdown.wait(30):
            try:
                touch_heartbeat()
            except Exception as exc:
                logger.warning("worker heartbeat failed: %s", exc)

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
