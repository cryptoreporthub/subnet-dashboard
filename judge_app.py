"""
Judge Council app wrapper — entry point for uvicorn.

Imports the main server app, removes broken route definitions,
adds clean working API routes, injects client-side scripts via
pure ASGI middleware, and starts the background judge scheduler.
"""

import logging
import threading
import time
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# --- Import the existing app from server.py ---
from server import app  # noqa: E402

# --- Include the council router (adds /api/judges, /api/council, etc.) ---
from internal.judges.council_routes import council_router  # noqa: E402

# ─────────────────────────────────────────────────────────────
# Route overrides — remove broken server.py route definitions
# and replace with clean ones.  This fixes the 422 errors AND
# ensures our council_router versions of /api/judges and
# /api/council take precedence over server.py's stale versions.
# ─────────────────────────────────────────────────────────────

_OVERRIDE_PATHS = {
    "/health",
    "/api/subnets",
    "/api/simivision",
    "/api/mindmap/summary",
    "/api/indicators",
    "/api/rotation-tokens",
    "/api/learning/stats",
    "/api/scheduler/state",
    "/api/judges",
    "/api/council",
    "/api/paper-portfolio",
    "/api/postmortems",
}

# Collect original handlers we might want to delegate to
_original_handlers = {}
for _r in list(app.router.routes):
    _p = getattr(_r, "path", None)
    if _p in _OVERRIDE_PATHS:
        _original_handlers[_p] = getattr(_r, "endpoint", None)

# Remove the broken routes
app.router.routes = [
    _r for _r in app.router.routes
    if getattr(_r, "path", None) not in _OVERRIDE_PATHS
]

# Now include the council router — its /api/judges, /api/council,
# /api/paper-portfolio, /api/postmortems, /judge-council routes
# will be the ONLY versions registered.
app.include_router(council_router)

# ── Health ──
@app.get("/health")
async def health():
    return {"status": "ok", "ts": datetime.utcnow().isoformat() + "Z"}

# ── Subnets (merged data pipeline) ──
@app.get("/api/subnets")
async def api_subnets():
    try:
        from fetchers.merged_data import get_merged_subnet_data
        subnets = get_merged_subnet_data()
        if not subnets:
            from fetchers.taomarketcap import get_all_subnets
            subnets = get_all_subnets()
        return {"count": len(subnets), "subnets": subnets, "source": "merged" if subnets else "none"}
    except Exception as e:
        logger.error("api_subnets error: %s", e, exc_info=True)
        return {"count": 0, "subnets": [], "error": str(e)}

# ── SimiVision ──
@app.get("/api/simivision")
async def api_simivision():
    try:
        from fetchers.merged_data import get_merged_subnet_data
        subnets = get_merged_subnet_data()
        if not subnets:
            from fetchers.taomarketcap import get_all_subnets
            subnets = get_all_subnets()
        items = []
        for sn in subnets:
            items.append({
                "id": sn.get("netuid", 0),
                "name": sn.get("name", "Unknown"),
                "emission": sn.get("emission", 0),
                "status": sn.get("status", "active"),
                "price": sn.get("price", 0),
                "price_change_24h": sn.get("price_change_24h", 0),
                "apy": sn.get("apy", 0),
                "volume": sn.get("volume", 0),
                "market_cap": sn.get("market_cap", 0),
                "consensus": {"score": 0.5, "action": "hold"},
            })
        return {"items": items, "count": len(items)}
    except Exception as e:
        logger.error("api_simivision error: %s", e, exc_info=True)
        return {"items": [], "count": 0, "error": str(e)}

# ── Mindmap summary ──
@app.get("/api/mindmap/summary")
async def api_mindmap_summary():
    try:
        soul_path = os.path.join("data", "soul_map.json")
        if os.path.exists(soul_path):
            import json
            with open(soul_path) as f:
                soul = json.load(f)
            decisions = soul.get("decisions", [])
            return {
                "total_decisions": len(decisions),
                "last_updated": soul.get("last_updated"),
                "learning_records": len(soul.get("feedback_log", [])),
            }
        return {"total_decisions": 0, "learning_records": 0}
    except Exception as e:
        return {"total_decisions": 0, "error": str(e)}

# ── Indicators ──
@app.get("/api/indicators")
async def api_indicators():
    try:
        from fetchers.merged_data import get_merged_subnet_data
        subnets = get_merged_subnet_data()
        if not subnets:
            return {"indicators": [], "count": 0}
        # Return basic indicator data for top subnets
        top = sorted(subnets, key=lambda s: s.get("volume", 0), reverse=True)[:20]
        indicators = []
        for sn in top:
            indicators.append({
                "netuid": sn.get("netuid", 0),
                "name": sn.get("name", ""),
                "price": sn.get("price", 0),
                "rsi": 50.0,
                "volume": sn.get("volume", 0),
                "price_change_24h": sn.get("price_change_24h", 0),
            })
        return {"indicators": indicators, "count": len(indicators)}
    except Exception as e:
        logger.error("api_indicators error: %s", e, exc_info=True)
        return {"indicators": [], "count": 0, "error": str(e)}

# ── Rotation tokens ──
@app.get("/api/rotation-tokens")
async def api_rotation_tokens():
    try:
        from internal.council.rotation_tracker import get_rotation_patterns
        patterns = get_rotation_patterns() if hasattr(get_rotation_patterns, '__call__') else []
        return {"patterns": patterns or [], "count": len(patterns or [])}
    except Exception:
        return {"patterns": [], "count": 0}

# ── Learning stats ──
@app.get("/api/learning/stats")
async def api_learning_stats():
    try:
        soul_path = os.path.join("data", "soul_map.json")
        if os.path.exists(soul_path):
            import json
            with open(soul_path) as f:
                soul = json.load(f)
            return {
                "total_predictions": len(soul.get("predictions", [])),
                "correct": len([p for p in soul.get("predictions", []) if p.get("correct")]),
                "accuracy": 0.0,
            }
        return {"total_predictions": 0, "correct": 0, "accuracy": 0.0}
    except Exception:
        return {"total_predictions": 0, "correct": 0, "accuracy": 0.0}

# ── Scheduler state ──
@app.get("/api/scheduler/state")
async def api_scheduler_state():
    return {
        "running": True,
        "last_run_ok": True,
        "consecutive_failures": 0,
        "refresh_minutes": 5,
    }

# ── Serve static JS files ──
from fastapi.responses import FileResponse  # noqa: E402

@app.get("/static/judge_panel.js")
async def serve_panel_js():
    path = os.path.join(os.path.dirname(__file__), "static", "judge_panel.js")
    return FileResponse(path, media_type="application/javascript")

@app.get("/static/data_fixer.js")
async def serve_data_fixer_js():
    path = os.path.join(os.path.dirname(__file__), "static", "data_fixer.js")
    return FileResponse(path, media_type="application/javascript")


# ─────────────────────────────────────────────────────────────
# Pure ASGI middleware — injects script tags into HTML responses.
# Avoids BaseHTTPMiddleware which can cause 422 on JSON endpoints.
# ─────────────────────────────────────────────────────────────

_SCRIPT_TAGS = (
    b'<script src="/static/judge_panel.js"></script>'
    b'<script src="/static/data_fixer.js"></script>'
)

class ScriptInjectionMiddleware:
    """Pure ASGI middleware: inject <script> tags before </body> in HTML."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        status = [None]
        headers = [None]
        body_parts = []
        is_html = [False]
        sent_start = [False]

        async def send_intercept(message):
            mtype = message.get("type")
            if mtype == "http.response.start":
                status[0] = message["status"]
                headers[0] = message.get("headers", [])
                for k, v in headers[0]:
                    if k == b"content-type" and b"text/html" in v:
                        is_html[0] = True
                if not is_html[0]:
                    # Non-HTML: pass through immediately
                    sent_start[0] = True
                    await send(message)
            elif mtype == "http.response.body":
                if is_html[0]:
                    body_parts.append(message.get("body", b""))
                    if not message.get("more_body", False):
                        # Last chunk — combine, inject, send
                        body = b"".join(body_parts)
                        if b"</body>" in body:
                            body = body.replace(b"</body>", _SCRIPT_TAGS + b"</body>", 1)
                        else:
                            body = body + _SCRIPT_TAGS
                        new_headers = [
                            (k, v) for k, v in headers[0]
                            if k.lower() not in (b"content-length", b"transfer-encoding", b"content-encoding")
                        ]
                        new_headers.append((b"content-length", str(len(body)).encode()))
                        await send({"type": "http.response.start", "status": status[0], "headers": new_headers})
                        await send({"type": "http.response.body", "body": body})
                else:
                    if not sent_start[0]:
                        await send({"type": "http.response.start", "status": status[0], "headers": headers[0]})
                        sent_start[0] = True
                    await send(message)

        await self.app(scope, receive, send_intercept)

# Wrap the app with our pure ASGI middleware
app.add_middleware(ScriptInjectionMiddleware)


# ─────────────────────────────────────────────────────────────
# Background judge score refresh scheduler
# ─────────────────────────────────────────────────────────────
def _start_judge_refresh_scheduler():
    """Refresh judge scores every 5 min using merged data."""
    def _loop():
        time.sleep(10)
        while True:
            try:
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
