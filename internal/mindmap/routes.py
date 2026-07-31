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

# get_mindmap_graph() -> build_mindmap_state() -> select_hourly_pick() reloads
# council weight files from disk per subnet scored, so a single build can take
# minutes. Without dedup, repeated polling (the frontend, or any monitor) fans
# out into N independent multi-minute computations that exhaust the whole
# AnyIO thread pool -> every other route (incl. "/") starts timing out too
# (production incident: /health stayed up, but "/" and pump-alerts still 503'd
# once enough concurrent mindmap builds piled up). Cache + serialize per focus
# key so at most one slow build is ever in flight.
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
