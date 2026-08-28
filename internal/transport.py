"""Transport-level gzip + immutable static caching, applied outside server.py.

PR #894 wired GZipMiddleware + immutable /static/* headers inside server.py.
That file is now the center of the #1058 hydration work, so this module applies
the same transport behavior as an ASGI wrapper (see asgi_entry.py) instead of
touching server.py.

Two differences from #894, both intentional:

- GZip skips /api/simivision/chat: with stream=true it returns an SSE
  StreamingResponse, and gzip buffering would stall per-event flushing.
- Immutable caching applies ONLY to the assets fingerprinted by
  internal/static_version.py (the STATIC_V token). Everything else under
  /static/* keeps its existing conservative cache headers, so an unlisted
  asset can never be pinned for a year by accident.
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.middleware.gzip import GZipMiddleware

_IMMUTABLE = "public, max-age=31536000, immutable"
_SSE_PATHS = ("/api/simivision/chat",)


def _fingerprinted_static_paths() -> frozenset:
    try:
        from internal.static_version import _ASSETS
    except Exception:
        return frozenset()
    return frozenset("/static/{}/{}".format(d, n) for d, n in _ASSETS)


class StaticCacheHeaders:
    """Immutable Cache-Control for fingerprinted /static/* assets only."""

    def __init__(self, app):
        self.app = app
        self.fingerprinted = _fingerprinted_static_paths()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "") in self.fingerprinted:
            async def send_with_cache(message):
                if message["type"] == "http.response.start":
                    message.setdefault("headers", [])
                    headers = MutableHeaders(scope=message)
                    headers["Cache-Control"] = _IMMUTABLE
                await send(message)

            await self.app(scope, receive, send_with_cache)
            return

        await self.app(scope, receive, send)


class SelectiveGZip:
    """GZip all responses except SSE endpoints, which need per-event flushing."""

    def __init__(self, app, minimum_size: int = 500):
        self.app = app
        self.gzipped = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "") in _SSE_PATHS:
            await self.app(scope, receive, send)
            return

        await self.gzipped(scope, receive, send)


def wrap(app):
    """Return the transport-wrapped ASGI callable for the given FastAPI app."""
    return StaticCacheHeaders(SelectiveGZip(app))
