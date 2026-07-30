"""Middleware: proxy volume-backed APIs to worker when split_v2 web has no volume."""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class WorkerVolumeProxyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        flag = os.environ.get("DISABLE_WORKER_PROXY", "").strip().lower()
        if flag in ("1", "true", "yes", "on"):
            return await call_next(request)
        from internal.worker_proxy import (
            proxy_get_to_worker,
            proxy_post_to_worker,
            should_proxy_path,
            should_proxy_write_path,
        )

        path = request.url.path
        if request.method == "GET" and should_proxy_path(path):
            return await proxy_get_to_worker(request)
        if should_proxy_write_path(request.method, path):
            return await proxy_post_to_worker(request)
        return await call_next(request)
