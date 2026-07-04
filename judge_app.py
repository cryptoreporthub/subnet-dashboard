"""
Judge Council app wrapper.

Imports the main server app, adds the Judge Council router,
and starts the background judge score refresh scheduler.
Panel is injected via the judge_council.html template.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

# --- Import the existing app from server.py ---
from server import app  # noqa: E402

# --- Include the council router ---
from internal.judges.council_routes import council_router  # noqa: E402

app.include_router(council_router)

# --- Background judge score refresh scheduler ---
def _start_judge_refresh_scheduler():
    """Refresh judge scores in background every 5 minutes."""
    def _loop():
        time.sleep(10)
        while True:
            try:
                from fetchers.taomarketcap import get_all_subnets
                from internal.judges.subnet_judges import score_all_subnets
                subnets_data = get_all_subnets()
                if subnets_data:
                    score_all_subnets(subnets_data)
                    logger.info("Judge scores refreshed (%d subnets)", len(subnets_data))
            except Exception as e:
                logger.warning("Judge refresh failed: %s", e)
            time.sleep(300)
    t = threading.Thread(target=_loop, daemon=True)
    t.start()


_start_judge_refresh_scheduler()

__all__ = ["app"]
