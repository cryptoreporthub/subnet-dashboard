"""
Judge Council app wrapper.

Imports the main server app, adds the Judge Council router,
starts the background judge score refresh scheduler, and
injects a Judge Council panel into HTML pages.
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

# --- Middleware: inject Judge Council panel into HTML pages ---
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.responses import Response, HTMLResponse  # noqa: E402

PANEL_HTML = """<div id="judge-council-panel" style="position:fixed;bottom:20px;right:20px;background:#1a1a2e;border:1px solid #c99a4b;border-radius:12px;padding:16px;z-index:9999;box-shadow:0 4px 20px rgba(0,0,0,0.5);max-width:320px;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
    <span style="font-size:20px;">\u2696\ufe0f</span>
    <span style="color:#c99a4b;font-weight:bold;font-size:14px;">Judge Council</span>
  </div>
  <p style="color:#aaa;font-size:12px;margin:0 0 10px 0;">AI judges evaluating subnet performance</p>
  <a href="/judge-council" style="display:inline-block;background:#c99a4b;color:#1a1a2e;padding:8px 16px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:bold;">View Council \u2192</a>
</div>"""


class JudgeCouncilLinkMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            return response
        try:
            # Prefer response.body (available on HTMLResponse/TemplateResponse after rendering)
            # Fall back to body_iterator for raw StreamingResponse
            html = None
            if hasattr(response, "body") and response.body:
                html = response.body.decode("utf-8", errors="ignore")
            else:
                body = b""
                async for chunk in response.body_iterator:
                    body += chunk
                html = body.decode("utf-8", errors="ignore")
            
            if not html or "</body>" not in html:
                return response
            
            html = html.replace("</body>", PANEL_HTML + "</body>")
            new_body = html.encode("utf-8")
            
            # Copy safe headers from original
            safe_headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in ("content-length", "transfer-encoding", "content-encoding")
            }
            
            return Response(
                content=new_body,
                media_type="text/html",
                status_code=response.status_code,
                headers=safe_headers,
            )
        except Exception as e:
            logger.warning("Judge council injection failed: %s", e)
            return response


app.add_middleware(JudgeCouncilLinkMiddleware)

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
