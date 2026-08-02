"""GET /api/mindmap/graph — explorable node/edge graph (Agent B mounts router)."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query
from starlette.concurrency import run_in_threadpool

from internal.mindmap.graph import get_mindmap_graph

logger = logging.getLogger(__name__)

mindmap_graph_router = APIRouter(tags=["mindmap-graph"])

# Graph build used to call build_mindmap_state() (hourly-pick scoring + every
# panel summary) and could run for minutes under load. get_mindmap_graph() now
# skips that path, but we still cache + serialize per focus so concurrent
# polls share one in-flight trail/integration build.
_CACHE_TTL_SECONDS = 30
_BUILD_WAIT_TIMEOUT_SECONDS = 8.0
MINDMAP_GRAPH_HANDLER_TIMEOUT = float(os.environ.get("MINDMAP_GRAPH_HANDLER_TIMEOUT_SECONDS", "12"))
_cache: Dict[Any, Dict[str, Any]] = {}
_cache_lock = threading.Lock()
_build_locks: Dict[Any, threading.Lock] = {}


def _build_lock_for(key: Any) -> threading.Lock:
    with _cache_lock:
        lock = _build_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _build_locks[key] = lock
        return lock


def _cached_or_build(focus: Optional[int]) -> Dict[str, Any]:
    with _cache_lock:
        cached = _cache.get(focus)
    if cached and time.time() - cached["at"] < _CACHE_TTL_SECONDS:
        return cached["data"]

    lock = _build_lock_for(focus)
    acquired = lock.acquire(timeout=_BUILD_WAIT_TIMEOUT_SECONDS)
    try:
        with _cache_lock:
            cached = _cache.get(focus)
        if cached and time.time() - cached["at"] < _CACHE_TTL_SECONDS:
            return cached["data"]
        if not acquired:
            # Another request is already building this key and it's taking a
            # while — serve stale cache rather than pile up more waiters.
            if cached:
                return cached["data"]
            return {"status": "warming", "nodes": [], "edges": []}
        data = get_mindmap_graph(focus_netuid=focus)
        with _cache_lock:
            _cache[focus] = {"at": time.time(), "data": data}
        return data
    finally:
        if acquired:
            lock.release()


def _stale_graph(focus: Optional[int]) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        cached = _cache.get(focus)
    if cached and isinstance(cached.get("data"), dict):
        return dict(cached["data"])
    return None


def _graph_timeout_payload(focus: Optional[int]) -> Dict[str, Any]:
    stale = _stale_graph(focus)
    if stale:
        out = dict(stale)
        out["status"] = "cached"
        out["detail"] = "Graph build timed out — serving last-good trail."
        return out
    try:
        from internal.learning.mindmap_aggregator import _build_integration_status

        integration_status = _build_integration_status()
    except Exception:
        integration_status = {}
    return {
        "status": "timeout",
        "nodes": [],
        "edges": [],
        "integration_status": integration_status,
        "detail": "Graph build timed out — retry shortly.",
    }


@mindmap_graph_router.get("/api/mindmap/graph")
async def api_mindmap_graph(focus: int | None = Query(default=None, ge=1)):
    try:
        return await asyncio.wait_for(
            run_in_threadpool(_cached_or_build, focus),
            timeout=MINDMAP_GRAPH_HANDLER_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("mindmap-graph timed out after %.1fs", MINDMAP_GRAPH_HANDLER_TIMEOUT)
        return _graph_timeout_payload(focus)
    except ImportError as exc:
        return {"status": "unavailable", "nodes": [], "edges": [], "detail": str(exc)}
    except Exception as exc:
        logger.warning("mindmap graph endpoint failed: %s", exc)
        return {"status": "success", "nodes": [], "edges": []}
