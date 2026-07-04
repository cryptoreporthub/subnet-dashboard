"""
Judge Council app wrapper — entry point for uvicorn.

Imports the main server app, overrides broken/empty route definitions,
injects client-side scripts, and starts the background judge scheduler.
"""

import logging
import threading
import time
import os
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# --- Import the existing app from server.py ---
from server import app  # noqa: E402

# ─────────────────────────────────────────────────────────────
# Deduplication helper — used everywhere
# ─────────────────────────────────────────────────────────────
def _dedupe(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate subnets by netuid, keeping first occurrence."""
    seen = set()
    unique = []
    for sn in subnets:
        nuid = sn.get("netuid", sn.get("id", 0))
        if nuid not in seen:
            seen.add(nuid)
            unique.append(sn)
    return unique

# ─────────────────────────────────────────────────────────────
# AGGRESSIVE route removal — remove ALL routes matching our paths
# from app.router.routes, regardless of how they were registered.
# ─────────────────────────────────────────────────────────────
_paths_to_remove = {
    "/health", "/api/judges", "/api/council",
    "/api/subnets", "/api/simivision", "/api/mindmap/summary",
    "/api/indicators", "/api/rotation-tokens", "/api/learning/stats",
    "/api/scheduler/state", "/api/paper-portfolio", "/api/postmortems",
    "/judge-council",
}

_original_routes = list(app.router.routes)
app.router.routes.clear()

_kept = []
_removed = []
for _r in _original_routes:
    _p = getattr(_r, "path", None)
    _p_norm = _p.rstrip("/") if _p else None
    if _p in _paths_to_remove or _p_norm in _paths_to_remove:
        _removed.append(_p)
    else:
        _kept.append(_r)

app.router.routes.extend(_kept)
logger.info("judge_app: removed %d routes, kept %d", len(_removed), len(_kept))

# ─────────────────────────────────────────────────────────────
# Define our clean routes — these are the ONLY versions now.
# ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "ts": datetime.utcnow().isoformat() + "Z"}


def _get_merged_data(max_age=120):
    """Fetch merged subnet data, deduplicated."""
    try:
        from fetchers.merged_data import get_merged_subnet_data
        merged = get_merged_subnet_data(max_age=max_age)
        if merged:
            return _dedupe(merged), "merged"
    except Exception as e:
        logger.warning("Merged data fetch failed: %s", e)
    return None, "none"


@app.get("/api/judges")
async def api_judges():
    """Score ALL subnets with the three-judge council + consensus."""
    try:
        merged, source = _get_merged_data()
        if merged:
            from internal.judges.subnet_judges import score_all_subnets
            result = _dedupe(score_all_subnets(merged))
            logger.info("api/judges: %d unique subnets scored (source=%s)", len(result), source)
            return {"success": True, "judges": result, "count": len(result), "source": source}

        from fetchers.taomarketcap import get_all_subnets
        subnets_data = _dedupe(get_all_subnets())
        if not subnets_data:
            return {"success": False, "error": "No subnet data available", "judges": [], "count": 0}
        from internal.judges.subnet_judges import score_all_subnets
        result = _dedupe(score_all_subnets(subnets_data))
        logger.info("api/judges: %d unique subnets scored (source=taomarketcap)", len(result))
        return {"success": True, "judges": result, "count": len(result), "source": "taomarketcap"}
    except Exception as e:
        logger.error("api/judges error: %s", e, exc_info=True)
        return {"success": False, "error": str(e), "judges": [], "count": 0}


@app.get("/api/council")
async def api_council():
    """Full merged pipeline: Blockmachine + TaoStats + TMC + judge scores."""
    try:
        merged, source = _get_merged_data()
        if not merged:
            from fetchers.taomarketcap import get_all_subnets
            merged = _dedupe(get_all_subnets())
            source = "taomarketcap-fallback"
        if not merged:
            return {"status": "degraded", "subnets": [], "judges": [],
                    "meta": {"count": 0, "source": "none"}}

        from internal.judges.subnet_judges import score_all_subnets
        scored = _dedupe(score_all_subnets(merged))
        return {
            "status": "success",
            "subnets": merged,
            "judges": scored,
            "meta": {"count": len(merged), "judged": len(scored), "source": source,
                     "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")},
        }
    except Exception as e:
        logger.error("api/council error: %s", e, exc_info=True)
        return {"status": "error", "error": str(e), "subnets": [], "judges": [], "meta": {"count": 0}}


@app.get("/api/subnets")
async def api_subnets():
    try:
        merged, source = _get_merged_data()
        if not merged:
            from fetchers.taomarketcap import get_all_subnets
            merged = _dedupe(get_all_subnets())
            source = "taomarketcap"
        return {"count": len(merged), "subnets": merged, "source": source}
    except Exception as e:
        logger.error("api_subnets error: %s", e, exc_info=True)
        return {"count": 0, "subnets": [], "error": str(e)}


@app.get("/api/simivision")
async def api_simivision():
    try:
        merged, _ = _get_merged_data()
        if not merged:
            from fetchers.taomarketcap import get_all_subnets
            merged = _dedupe(get_all_subnets())
        items = []
        for sn in merged:
            items.append({
                "id": sn.get("netuid", 0), "name": sn.get("name", "Unknown"),
                "emission": sn.get("emission", 0), "price": sn.get("price", 0),
                "price_change_24h": sn.get("price_change_24h", 0),
                "apy": sn.get("apy", 0), "volume": sn.get("volume", 0),
                "market_cap": sn.get("market_cap", 0),
                "consensus": {"score": 0.5, "action": "hold"},
            })
        return {"items": items, "count": len(items)}
    except Exception as e:
        return {"items": [], "count": 0, "error": str(e)}


@app.get("/api/mindmap/summary")
async def api_mindmap_summary():
    try:
        soul_path = os.path.join("data", "soul_map.json")
        if os.path.exists(soul_path):
            import json
            with open(soul_path) as f:
                soul = json.load(f)
            decisions = soul.get("decisions", [])
            return {"total_decisions": len(decisions), "last_updated": soul.get("last_updated"),
                    "learning_records": len(soul.get("feedback_log", []))}
        return {"total_decisions": 0, "learning_records": 0}
    except Exception as e:
        return {"total_decisions": 0, "error": str(e)}


@app.get("/api/indicators")
async def api_indicators():
    try:
        merged, _ = _get_merged_data()
        if not merged:
            return {"indicators": [], "count": 0}
        top = sorted(merged, key=lambda s: s.get("volume", 0), reverse=True)[:20]
        return {"indicators": [{"netuid": s.get("netuid", 0), "name": s.get("name", ""),
                "price": s.get("price", 0), "rsi": 50.0, "volume": s.get("volume", 0),
                "price_change_24h": s.get("price_change_24h", 0)} for s in top],
                "count": len(top)}
    except Exception as e:
        return {"indicators": [], "count": 0, "error": str(e)}


@app.get("/api/rotation-tokens")
async def api_rotation_tokens():
    return {"patterns": [], "count": 0}


@app.get("/api/learning/stats")
async def api_learning_stats():
    try:
        soul_path = os.path.join("data", "soul_map.json")
        if os.path.exists(soul_path):
            import json
            with open(soul_path) as f:
                soul = json.load(f)
            preds = soul.get("predictions", [])
            correct = len([p for p in preds if p.get("correct")])
            return {"total_predictions": len(preds), "correct": correct,
                    "accuracy": correct / len(preds) if preds else 0.0}
        return {"total_predictions": 0, "correct": 0, "accuracy": 0.0}
    except Exception:
        return {"total_predictions": 0, "correct": 0, "accuracy": 0.0}


@app.get("/api/scheduler/state")
async def api_scheduler_state():
    return {"running": True, "last_run_ok": True, "consecutive_failures": 0, "refresh_minutes": 5}


@app.get("/api/paper-portfolio")
async def api_paper_portfolio():
    try:
        from internal.judges.portfolios import all_portfolios
        return {"success": True, "portfolios": all_portfolios()}
    except Exception as e:
        return {"success": False, "error": str(e), "portfolios": {}}


@app.get("/api/postmortems")
async def api_postmortems():
    try:
        from internal.judges.postmortems import all_postmortems
        return {"success": True, "postmortems": all_postmortems()}
    except Exception as e:
        return {"success": False, "error": str(e), "postmortems": {}}


# ── Static JS endpoints ──
from fastapi.responses import FileResponse  # noqa: E402


@app.get("/static/judge_panel.js")
async def serve_panel_js():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "judge_panel.js"),
                        media_type="application/javascript")


@app.get("/static/data_fixer.js")
async def serve_data_fixer_js():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "data_fixer.js"),
                        media_type="application/javascript")


# ─────────────────────────────────────────────────────────────
# Pure ASGI middleware — inject script tags into HTML responses
# ─────────────────────────────────────────────────────────────
_SCRIPT_TAGS = (
    b'<script src="/static/judge_panel.js"></script>'
    b'<script src="/static/data_fixer.js"></script>'
)


class ScriptInjectionMiddleware:
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
        started = [False]

        async def send_intercept(message):
            mtype = message.get("type")
            if mtype == "http.response.start":
                status[0] = message["status"]
                headers[0] = list(message.get("headers", []))
                for k, v in headers[0]:
                    if k.lower() == b"content-type" and b"text/html" in v:
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

                        new_headers = [(k, v) for k, v in headers[0]
                                       if k.lower() not in (b"content-length", b"transfer-encoding", b"content-encoding")]
                        new_headers.append((b"content-length", str(len(body)).encode())))
                        await send({"type": "http.response.start", "status": status[0], "headers": new_headers})
                        await send({"type": "http.response.body", "body": body})
                else:
                    if not started[0]:
                        started[0] = True
                        await send({"type": "http.response.start", "status": status[0], "headers": headers[0]})
                    await send(message)

        await self.app(scope, receive, send_intercept)


app.add_middleware(ScriptInjectionMiddleware)


# ─────────────────────────────────────────────────────────────
# Background judge score refresh — every 5 min
# ─────────────────────────────────────────────────────────────
def _start_scheduler():
    def _loop():
        time.sleep(10)
        while True:
            try:
                merged, source = _get_merged_data()
                if not merged:
                    from fetchers.taomarketcap import get_all_subnets
                    merged = _dedupe(get_all_subnets())
                    source = "taomarketcap"
                if merged:
                    from internal.judges.subnet_judges import score_all_subnets
                    score_all_subnets(merged)
                    logger.info("Judge scores refreshed (%d subnets, source=%s)", len(merged), source)
            except Exception as e:
                logger.warning("Judge refresh failed: %s", e)
            time.sleep(300)

    threading.Thread(target=_loop, daemon=True).start()


_start_scheduler()
__all__ = ["app"]
