"""Send INFO from the heavy-job gate and resolver scheduler to stdout (Fly/Axiom).

No entrypoint configured logging, so the root logger stayed at WARNING with no
handler and logger.info() was dropped. Only these two loggers are raised to INFO
so prod log volume from the rest of the app is unchanged.
"""

from __future__ import annotations

import logging
import sys

INFO_LOGGERS = (
    "internal.heavy_job_gate",
    "internal.council.resolver_scheduler",
)
_HANDLER_NAME = "app-info-stdout"


def configure_app_logging() -> None:
    root = logging.getLogger()
    if not any(h.get_name() == _HANDLER_NAME for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        root.addHandler(handler)
    for name in INFO_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)
