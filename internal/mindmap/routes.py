"""GET /api/mindmap/graph — explorable node/edge graph (Agent B mounts router)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from starlette.concurrency import run_in_threadpool

from internal.mindmap.graph import get_mindmap_graph

logger = logging.getLogger(__name__)

mindmap_graph_router = APIRouter(tags=["mindmap-graph"])


@mindmap_graph_router.get("/api/mindmap/graph")
async def api_mindmap_graph(focus: int | None = Query(default=None, ge=1)):
    # get_mindmap_graph() walks council/hourly-pick/pump-ladder state and has
    # repeatedly grown expensive synchronous sub-calls (TaoStats network I/O,
    # a large soul_map.json rewrite, hourly-pick technical scoring) that each
    # wedged the whole event loop when run inline. Route the call through the
    # thread pool so no matter what runs inside it, /health and every other
    # request stay responsive even if this one is slow.
    try:
        return await run_in_threadpool(get_mindmap_graph, focus_netuid=focus)
    except ImportError as exc:
        return {"status": "unavailable", "nodes": [], "edges": [], "detail": str(exc)}
    except Exception as exc:
        logger.warning("mindmap graph endpoint failed: %s", exc)
        return {"status": "success", "nodes": [], "edges": []}
