"""ASGI entry point for web: server.app wrapped in transport-level gzip + cache.

Why not "server:app" directly: PR #894's transport perf changes (gzip +
immutable static caching) are applied as an ASGI wrapper here so server.py
itself is untouched (it is the center of the #1058 hydration work).

Uvicorn boots this via scripts/run_web_with_guard.py (Procfile + Fly web).
The dedicated worker HTTP serves ``server:app`` via the same launcher with
``UVICORN_TARGET=server:app`` so rate-limit keys share ``UVICORN_WEB_KWARGS``.
"""

from __future__ import annotations

import server
from internal.transport import wrap

_inner_app = server.app


class WrappedApp:
    """Expose the inner FastAPI app's attributes (routes, etc.) for tests."""

    def __init__(self, inner):
        self._inner = inner
        self._wrapped = wrap(inner)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def __call__(self, scope, receive, send):
        await self._wrapped(scope, receive, send)


app = WrappedApp(_inner_app)
