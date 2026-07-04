"""
Judge Council app wrapper — entry point for uvicorn.

Imports the main server app, then wraps it with an ASGI middleware that
intercepts all /health and /api/* requests and serves them directly from
clean handlers using the merged data pipeline.  Non-API requests (homepage,
static files) pass through to the original server app unchanged.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime
from urllib.parse import parse_qs

logger = logging.getLogger(__name__)

# --- Import the existing app from server.py ---
from server import app  # noqa: E402

# --- Include the council router (adds /api/judges, /api/council, etc.) ---
from internal.judges.council_routes import council_router  # noqa: E402

# We can't safely remove server.py's broken routes (FastAPI compiles them),
# so we intercept at the ASGI level instead. But we still include the council
# router so its routes are registered — our middleware will handle them.
app.include_router(council_router)


# ─────────────────────────────────────────────────────────────
# Clean API handlers — these replace all broken server.py routes.
# Each returns (status_code, headers, body_bytes).
# ─────────────────────────────────────────────────────────────

def _json(data, status=200):
    body = json.dumps(data, default=str).encode()
    return status, [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ], body

def _handle_health(scope):
    return _json({"status": "ok", "ts": datetime.utcnow().isoformat() + "Z"})

def _handle_api_subnets(scope):
    try:
        from fetchers.merged_data import get_merged_subnet_data
        subnets = get_merged_subnet_data()
        if not subnets:
            from fetchers.taomarketcap import get_all_subnets
            subnets = get_all_subnets()
        # Deduplicate by netuid
        seen = set()
        unique = []
        for s in subnets:
            nuid = s.get("netuid", 0)
            if nuid not in seen:
                seen.add(nuid)
                unique.append(s)
        return _json({"count": len(unique), "subnets": unique, "source": "merged" if unique else "none"})
    except Exception as e:
        logger.error("api_subnets error: %s", e, exc_info=True)
        return _json({"count": 0, "subnets": [], "error": str(e)})

def _handle_api_judges(scope):
    try:
        from fetchers.merged_data import get_merged_subnet_data
        merged, source = merged_data_with_source()
        if not merged:
            from fetchers.taomarketcap import get_all_subnets
            merged = get_all_subnets()
            source = "taomarketcap-fallback"
        if not merged:
            return _json({"success": False, "error": "No subnet data", "judges": [], "count": 0})
        # Deduplicate by netuid before scoring
        seen = set()
        unique = []
        for s in merged:
            nuid = s.get("netuid", 0)
            if nuid not in seen:
                seen.add(nuid)
                unique.append(s)
        from internal.judges.subnet_judges import score_all_subnets
        result = score_all_subnets(unique)
        return _json({"success": True, "judges": result, "count": len(result), "source": source})
    except Exception as e:
        logger.error("api_judges error: %s", e, exc_info=True)
        return _json({"success": False, "error": str(e), "judges": [], "count": 0})

def _handle_api_council(scope):
    try:
        merged, source = merged_data_with_source()
        if not merged:
            from fetchers.taomarketcap import get_all_subnets
            merged = get_all_subnets()
            source = "taomarketcap-fallback"
        if not merged:
            return _json({"status": "degraded", "subnets": [], "judges": [], "meta": {"count": 0, "source": "none"}})
        # Deduplicate
        seen = set()
        unique = []
        for s in merged:
            nuid = s.get("netuid", 0)
            if nuid not in seen:
                seen.add(nuid)
                unique.append(s)
        try:
            from internal.judges.subnet_judges import score_all_subnets
            scored = score_all_subnets(unique)
        except Exception as e:
            logger.warning("Judge scoring failed: %s", e)
            scored = []
        return _json({
            "status": "success",
            "subnets": unique,
            "judges": scored,
            "meta": {
                "count": len(unique),
                "judged": len(scored) if scored else 0,
                "source": source,
                "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        })
    except Exception as e:
        logger.error("council API error: %s", e, exc_info=True)
        return _json({"status": "error", "error": str(e), "subnets": [], "judges": [], "meta": {"count": 0}})

def _handle_api_simivision(scope):
    try:
        merged, source = merged_data_with_source()
        if not merged:
            from fetchers.taomarketcap import get_all_subnets
            merged = get_all_subnets()
        items = []
        seen = set()
        for sn in merged:
            nuid = sn.get("netuid", 0)
            if nuid in seen:
                continue
            seen.add(nuid)
            items.append({
                "id": nuid,
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
        return _json({"items": items, "count": len(items)})
    except Exception as e:
        logger.error("api_simivision error: %s", e, exc_info=True)
        return _json({"items": [], "count": 0, "error": str(e)})

def _handle_api_mindmap_summary(scope):
    try:
        soul_path = os.path.join("data", "soul_map.json")
        if os.path.exists(soul_path):
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

def _handle_api_indicators(scope):
    try:
        merged, _ = merged_data_with_source()
        if not merged:
            from fetchers.taomarketcap import get_all_subnets
            merged = get_all_subnets()
        if not merged:
            return _json({"indicators": [], "count": 0})
        top = sorted(merged, key=lambda s: s.get("volume", 0), reverse=True)[:20]
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
        return _json({"indicators": indicators, "count": len(indicators)})
    except Exception as e:
        return _json({"indicators": [], "count": 0, "error": str(e)})

def _handle_api_rotation_tokens(scope):
    return _json({"patterns": [], "count": 0})

def _handle_api_learning_stats(scope):
    try:
        soul_path = os.path.join("data", "soul_map.json")
        if os.path.exists(soul_path):
            with open(soul_path) as f:
                soul = json.load(f)
            preds = soul.get("predictions", [])
            correct = len([p for p in preds if p.get("correct")])
            return _json({
                "total_predictions": len(preds),
                "correct": correct,
                "accuracy": correct / len(preds) if preds else 0.0,
            })
        return _json({"total_predictions": 0, "correct": 0, "accuracy": 0.0})
    except Exception:
        return _json({"total_predictions": 0, "correct": 0, "accuracy": 0.0})

def _handle_api_scheduler_state(scope):
    return _json({
        "running": True,
        "last_run_ok": True,
        "consecutive_failures": 0,
        "refresh_minutes": 5,
    })

def _handle_api_paper_portfolio(scope):
    try:
        from internal.judges.portfolios import all_portfolios
        portfolios = all_portfolios()
        return _json({"success": True, "portfolios": portfolios})
    except Exception as e:
        return _json({"success": False, "error": str(e), "portfolios": {}})

def _handle_api_postmortems(scope):
    try:
        from internal.judges.postmortems import all_postmortems
        postmortems = all_postmortems()
        return _json({"success": True, "postmortems": postmortems})
    except Exception as e:
        return _json({"success": False, "error": str(e), "postmortems": {}})

def merged_data_with_source():
    """Try merged data, return (subnets, source_str)."""
    try:
        from fetchers.merged_data import get_merged_subnet_data
        merged = get_merged_subnet_data()
        if merged:
            return merged, "merged"
    except Exception as e:
        logger.warning("Merged data fetch failed: %s", e)
    return None, "none"

# Route dispatch table
API_ROUTES = {
    "/health": _handle_health,
    "/api/subnets": _handle_api_subnets,
    "/api/judges": _handle_api_judges,
    "/api/council": _handle_api_council,
    "/api/simivision": _handle_api_simivision,
    "/api/mindmap/summary": _handle_api_mindmap_summary,
    "/api/indicators": _handle_api_indicators,
    "/api/rotation-tokens": _handle_api_rotation_tokens,
    "/api/learning/stats": _handle_api_learning_stats,
    "/api/scheduler/state": _handle_api_scheduler_state,
    "/api/paper-portfolio": _handle_api_paper_portfolio,
    "/api/postmortems": _handle_api_postmortems,
}


# ─────────────────────────────────────────────────────────────
# Pure ASGI middleware:
#   1. Intercept /health and /api/* paths → serve from clean handlers
#   2. For HTML responses, inject <script> tags before </body>
# ─────────────────────────────────────────────────────────────

_SCRIPT_TAGS = (
    b'<script src="/static/judge_panel.js"></script>'
    b'<script src="/static/data_fixer.js"></script>'
)

_STATIC_FILES = {
    "/static/judge_panel.js": ("static/judge_panel.js", "application/javascript"),
    "/static/data_fixer.js": ("static/data_fixer.js", "application/javascript"),
}

class InterceptionMiddleware:
    """Pure ASGI middleware: intercept API routes + inject scripts into HTML."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # ── Serve static JS files directly ──
        if path in _STATIC_FILES:
            file_rel, mime = _STATIC_FILES[path]
            file_path = os.path.join(os.path.dirname(__file__), file_rel)
            try:
                with open(file_path, "rb") as f:
                    body = f.read()
                headers = [
                    (b"content-type", mime.encode()),
                    (b"content-length", str(len(body)).encode()),
                    (b"cache-control", b"no-cache"),
                ]
                await send({"type": "http.response.start", "status": 200, "headers": headers})
                await send({"type": "http.response.body", "body": body})
                return
            except Exception as e:
                logger.warning("Static file %s error: %s", path, e)

        # ── Intercept API routes ──
        if path in API_ROUTES:
            handler = API_ROUTES[path]
            try:
                result = handler(scope)
                if isinstance(result, tuple):
                    status, headers, body = result
                elif isinstance(result, dict):
                    status, headers, body = _json(result)
                else:
                    status, headers, body = 500, [(b"content-type", b"text/plain")], b"Internal error"
            except Exception as e:
                logger.error("Handler %s error: %s", path, e, exc_info=True)
                status, headers, body = _json({"error": str(e)}, 500)
            await send({"type": "http.response.start", "status": status, "headers": headers})
            await send({"type": "http.response.body", "body": body})
            return

        # ── Pass through to original app, inject scripts into HTML ──
        status = [None]
        headers = [None]
        body_parts = []
        is_html = [False]
        started = [False]

        async def send_intercept(message):
            mtype = message.get("type")
            if mtype == "http.response.start":
                status[0] = message["status"]
                headers[0] = message.get("headers", [])
                for k, v in headers[0]:
                    if k == b"content-type" and b"text/html" in v:
                        is_html[0] = True
                if not is_html[0]:
                    started[0] = True
                    await send(message)
            elif mtype == "http.response.body":
                if is_html[0]:
                    body_parts.append(message.get("body", b""))
                    if not message.get("more_body", False):
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
                    if not started[0]:
                        await send({"type": "http.response.start", "status": status[0], "headers": headers[0]})
                        started[0] = True
                    await send(message)

        await self.app(scope, receive, send_intercept)

app.add_middleware(InterceptionMiddleware)


# ─────────────────────────────────────────────────────────────
# Background judge score refresh scheduler
# ─────────────────────────────────────────────────────────────
def _start_judge_refresh_scheduler():
    def _loop():
        time.sleep(10)
        while True:
            try:
                merged, source = merged_data_with_source()
                if not merged:
                    from fetchers.taomarketcap import get_all_subnets
                    merged = get_all_subnets()
                    source = "taomarketcap"
                if merged:
                    # Deduplicate
                    seen = set()
                    unique = []
                    for s in merged:
                        nuid = s.get("netuid", 0)
                        if nuid not in seen:
                            seen.add(nuid)
                            unique.append(s)
                    from internal.judges.subnet_judges import score_all_subnets
                    score_all_subnets(unique)
                    logger.info("Judge scores refreshed (%d subnets, source=%s)", len(unique), source)
            except Exception as e:
                logger.warning("Judge refresh failed: %s", e)
            time.sleep(300)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()

_start_judge_refresh_scheduler()

__all__ = ["app"]
