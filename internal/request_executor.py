"""Dedicated executor for request-time aggregation work.

Background build loops (learning-loop health, score scheduler, mindmap graph
build) saturate the default asyncio executor, which is capped at
``AIO_WORKER_POOL_SIZE`` (see server.py). Request-serving aggregation for the
council hero (resolver state, learning stats, mindmap graph) must NOT queue
behind that saturated pool, or the endpoints hang until the HTTP timeout and
serve stale/empty snapshots.

This module owns a small dedicated pool so request-time work always has
headroom, mirroring the ``_DASHBOARD_EXECUTOR`` pattern already used for
dashboard handlers.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

REQUEST_WORKER_POOL_SIZE = int(os.environ.get("REQUEST_WORKER_POOL_SIZE", "4"))

REQUEST_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(2, REQUEST_WORKER_POOL_SIZE),
    thread_name_prefix="request-work",
)


async def to_thread_timeout(
    fn: Callable[[], Any],
    timeout_s: float,
    *,
    label: str,
    executor: concurrent.futures.Executor | None = None,
) -> Any:
    """Run sync work on REQUEST_EXECUTOR with a hard asyncio wait budget."""
    pool = executor if executor is not None else REQUEST_EXECUTOR
    try:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(pool, fn),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning("%s timed out after %.1fs", label, timeout_s)
        raise
