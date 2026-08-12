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

import concurrent.futures
import os

REQUEST_WORKER_POOL_SIZE = int(os.environ.get("REQUEST_WORKER_POOL_SIZE", "4"))

REQUEST_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(2, REQUEST_WORKER_POOL_SIZE),
    thread_name_prefix="request-work",
)
