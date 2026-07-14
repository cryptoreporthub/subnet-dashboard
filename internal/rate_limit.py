"""slowapi rate limiting (audit #9)."""

from __future__ import annotations

import os
from typing import Callable, Optional, TypeVar

from slowapi import Limiter
from slowapi.util import get_remote_address

_STRICT_LIMIT = "30/minute"
_EXEMPT_EXACT = frozenset({"/health", "/api/health", "/metrics"})
_EXEMPT_PREFIXES = ("/static/",)

_limiter: Optional[Limiter] = None

F = TypeVar("F", bound=Callable)


def rate_limit_enabled() -> bool:
    return os.environ.get("ENABLE_RATE_LIMIT", "1").strip().lower() not in ("0", "false", "no")


def default_limit() -> str:
    return os.environ.get("RATE_LIMIT_DEFAULT", "120/minute")


def strict_limit() -> str:
    return _STRICT_LIMIT


def is_exempt_path(path: str) -> bool:
    if path in _EXEMPT_EXACT:
        return True
    if path == "/static" or path.startswith(_EXEMPT_PREFIXES):
        return True
    return False


def get_limiter() -> Optional[Limiter]:
    global _limiter
    if not rate_limit_enabled():
        return None
    if _limiter is None:
        _limiter = Limiter(
            key_func=get_remote_address,
            default_limits=[default_limit()],
        )
    return _limiter


def limit_or_noop(limit: str, *, override_defaults: bool = False):
    """Return slowapi limit decorator, or a no-op when rate limiting is disabled."""

    def decorator(func: F) -> F:
        lim = get_limiter()
        if lim is None:
            return func
        return lim.limit(limit, override_defaults=override_defaults)(func)

    return decorator


def mount_rate_limit(app) -> None:
    """Attach limiter, 429 handler, middleware, and exempt-path bypass when enabled."""
    if not rate_limit_enabled():
        return

    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware

    limiter = get_limiter()
    assert limiter is not None
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.middleware("http")
    async def _exempt_rate_limit_paths(request, call_next):
        if is_exempt_path(request.url.path):
            request.state._rate_limiting_complete = True
        return await call_next(request)
