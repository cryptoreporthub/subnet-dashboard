"""GET /api/mindmap/graph — explorable node/edge graph (Agent B mounts router)."""

from __future__ import annotations

import logging
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


@mindmap_graph_router.get("/api/mindmap/graph")
async def api_mindmap_graph(focus: int | None = Query(default=None, ge=1)):
    try:
        return await run_in_threadpool(_cached_or_build, focus)
    except ImportError as exc:
        return {"status": "unavailable", "nodes": [], "edges": [], "detail": str(exc)}
    except Exception as exc:
        logger.warning("mindmap graph endpoint failed: %s", exc)
        return {"status": "success", "nodes": [], "edges": []}
