"""Fly single-worker load shedding — keep /health responsive under hydrate storms."""

from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

_BYPASS_PATHS = frozenset({"/health", "/api/health", "/metrics"})
_BYPASS_PREFIXES = ("/static/",)
_ACQUIRE_TIMEOUT = float(os.environ.get("LOAD_SHED_ACQUIRE_SECONDS", "0.25"))
_MAX_IN_FLIGHT = max(1, int(os.environ.get("MAX_IN_FLIGHT_REQUESTS", "4")))

_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(_MAX_IN_FLIGHT)
    return _semaphore


def bypass_path(path: str) -> bool:
    if path in _BYPASS_PATHS:
        return True
    return path.startswith(_BYPASS_PREFIXES)


class LoadShedMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if bypass_path(request.url.path):
            return await call_next(request)
        sem = _get_semaphore()
        try:
            await asyncio.wait_for(sem.acquire(), timeout=_ACQUIRE_TIMEOUT)
        except asyncio.TimeoutError:
            return PlainTextResponse(
                "server busy — retry shortly",
                status_code=503,
                headers={"Retry-After": "10", "Cache-Control": "no-store"},
            )
        try:
            return await call_next(request)
        finally:
            sem.release()


def mount_load_shed(app) -> None:
    if os.environ.get("ENABLE_LOAD_SHED", "1").strip().lower() in ("0", "false", "no"):
        return
    app.add_middleware(LoadShedMiddleware)
