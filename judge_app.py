"""
Judge Council app wrapper.

Imports the main server app, adds the Judge Council router,
starts the background judge score refresh scheduler, and
injects a Judge Council script tag into HTML pages.
"""

import logging
import threading
import time
import os

logger = logging.getLogger(__name__)

# --- Import the existing app from server.py ---
from server import app  # noqa: E402

# --- Include the council router ---
from internal.judges.council_routes import council_router  # noqa: E402

app.include_router(council_router)

# --- Serve the panel JS ---
from fastapi.responses import FileResponse  # noqa: E402

PANEL_JS_PATH = os.path.join(os.path.dirname(__file__), "static", "judge_panel.js")

@app.get("/static/judge_panel.js")
async def serve_panel_js():
    return FileResponse(PANEL_JS_PATH, media_type="application/javascript")

# --- Middleware: inject script tag ONLY (minimal body change) ---
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.responses import Response  # noqa: E402

SCRIPT_TAG = b'<script src="/static/judge_panel.js"></script>'

class JudgeCouncilScriptMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            return response
        try:
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            if not body:
                return response
            if b"</body>" in body:
                body = body.replace(b"</body>", SCRIPT_TAG + b"</body>", 1)
            else:
                body = body + SCRIPT_TAG
            safe_headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in ("content-length", "transfer-encoding", "content-encoding")
            }
            return Response(content=body, media_type="text/html", status_code=response.status_code, headers=safe_headers)
        except Exception as e:
            logger.warning("Judge council script injection failed: %s", e)
            return response

app.add_middleware(JudgeCouncilScriptMiddleware)

# --- Background judge score refresh scheduler ---
def _start_judge_refresh_scheduler():
    """Refresh judge scores in background every 5 minutes using merged data."""
    def _loop():
        time.sleep(10)
        while True:
            try:
                # Try merged data pipeline first (Blockmachine + TaoStats + TMC)
                try:
                    from fetchers.merged_data import get_merged_subnet_data
                    subnets_data = get_merged_subnet_data()
                    source = "merged"
                except Exception as merged_exc:
                    logger.warning("Merged data unavailable, falling back to TMC: %s", merged_exc)
                    from fetchers.taomarketcap import get_all_subnets
                    subnets_data = get_all_subnets()
                    source = "taomarketcap"

                if subnets_data:
                    from internal.judges.subnet_judges import score_all_subnets
                    score_all_subnets(subnets_data)
                    logger.info("Judge scores refreshed (%d subnets, source=%s)", len(subnets_data), source)
            except Exception as e:
                logger.warning("Judge refresh failed: %s", e)
            time.sleep(300)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()

_start_judge_refresh_scheduler()

__all__ = ["app"]
