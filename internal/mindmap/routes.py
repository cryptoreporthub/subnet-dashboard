"""GET /api/mindmap/graph — explorable node/edge graph (Agent B mounts router)."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from internal.mindmap.graph import get_mindmap_graph

logger = logging.getLogger(__name__)

mindmap_graph_router = APIRouter(tags=["mindmap-graph"])


@mindmap_graph_router.get("/api/mindmap/graph")
async def api_mindmap_graph():
    try:
        return get_mindmap_graph()
    except ImportError as exc:
        return {"status": "unavailable", "nodes": [], "edges": [], "detail": str(exc)}
    except Exception as exc:
        logger.warning("mindmap graph endpoint failed: %s", exc)
        return {"status": "success", "nodes": [], "edges": []}
