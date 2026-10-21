"""Send INFO from the heavy-job gate, resolver scheduler and score-snapshot builder to stdout (Fly/Axiom).

No entrypoint configured logging, so the root logger stayed at WARNING with no
handler and logger.info() was dropped. Only these loggers are raised to INFO
so prod log volume from the rest of the app is unchanged.
"""

from __future__ import annotations

import logging
import os
import sys

INFO_LOGGERS = (
    "internal.heavy_job_gate",
    "internal.council.resolver_scheduler",
    "internal.council.score_snapshots",
    "live_subnets",
    "process_memory",
    "internal.background_boot",
)
_HANDLER_NAME = "app-info-stdout"


def configure_app_logging() -> None:
    root = logging.getLogger()
    if not any(h.get_name() == _HANDLER_NAME for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s pid=%(process)d %(levelname)s %(name)s %(message)s"
            )
        )
        root.addHandler(handler)
    for name in INFO_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)
    try:
        from internal.process_memory import start_rss_heartbeat

        start_rss_heartbeat(
            float(os.environ.get("PROCESS_RSS_LOG_INTERVAL_SECONDS", "120"))
        )
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "process RSS heartbeat not started: %s", exc
        )
