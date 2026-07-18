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
    from internal.background_boot import start_background_workers, stop_background_workers

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    start_background_workers()
    logger.info("background worker running (RUN_MODE=worker)")
    _shutdown.wait()
    stop_background_workers()
    logger.info("background worker stopped")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
