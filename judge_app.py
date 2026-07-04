"""
Judge Council app wrapper.

Imports the main server app, adds the Judge Council router,
starts the background judge score refresh scheduler, and
injects a floating Judge Council button into HTML pages.
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

# --- Middleware: inject floating Judge Council button into HTML pages ---
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402


class JudgeCouncilLinkMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            try:
                body = b""
                async for chunk in response.body_iterator:
                    body += chunk
                html = body.decode("utf-8", errors="ignore")
                if "</body>" in html:
                    button_html = (
                        "<div style=\"position:fixed;bottom:20px;right:20px;z-index:99999;\">"
                        "<a href=\"/judge-council\" style=\"background:#00ff41;color:#000;"
                        "padding:12px 20px;border-radius:8px;text-decoration:none;"
                        "font-weight:bold;font-family:monospace;font-size:14px;"
                        "box-shadow:0 0 15px #00ff41;\">"
                        "\u2696\ufe0f Judge Council"
                        "</a></div>"
                    )
                    html = html.replace("</body>", button_html + "</body>")
                    new_body = html.encode("utf-8")
                    response.body = new_body
                    response.headers["content-length"] = str(len(new_body))
            except Exception as e:
                logger.debug("Judge council injection skipped: %s", e)
        return response


app.add_middleware(JudgeCouncilLinkMiddleware)


# --- Background judge score refresh scheduler ---
def _start_judge_refresh_scheduler():
    """Refresh judge scores in background every 5 minutes."""
    def _loop():
        time.sleep(10)  # Let the app fully start first
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