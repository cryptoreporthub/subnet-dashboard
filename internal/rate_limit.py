"""slowapi rate limiting (audit #9)."""

from __future__ import annotations

import os
from typing import Callable, Mapping, Optional, TypeVar

from slowapi import Limiter

_STRICT_LIMIT = "30/minute"
_EXEMPT_EXACT = frozenset({"/health", "/api/health", "/api/ops/live", "/metrics", "/version"})
_EXEMPT_PREFIXES = ("/static/",)

_limiter: Optional[Limiter] = None

F = TypeVar("F", bound=Callable)


def on_fly() -> bool:
    return bool(os.environ.get("FLY_APP_NAME", "").strip())


def socket_peer_host(request) -> str:
    """ASGI TCP peer; must not pass through uvicorn ProxyHeadersMiddleware (proxy_headers=False)."""
    client = request.scope.get("client")
    if client:
        return str(client[0])
    return "unknown"


def client_ip_from_headers(headers: Mapping[str, str], fallback: str) -> str:
    """Shared key for shield telemetry: Fly-Client-IP on Fly; never X-Forwarded-For."""
    if on_fly():
        # Starlette Headers and shield._headers() both resolve case-insensitively.
        fly_ip = (headers.get("fly-client-ip") or "").strip()
        if fly_ip:
            return fly_ip
        return fallback or "unknown"
    return fallback or "unknown"


def client_ip(request) -> str:
    """slowapi key_func: Fly-Client-IP on Fly, else request.client; never X-Forwarded-For.

    On Fly, missing ``Fly-Client-IP`` means the request did not arrive through Fly's edge
    proxy as expected (e.g. another CDN in front). We deliberately do **not** parse
    ``X-Forwarded-For`` (client-spoofable; see #1633 /tl).

    **Assumption (not verified in this repo):** direct traffic to Fly's proxy yields a
    ``Fly-Client-IP`` header added by Fly Proxy and not spoofable by the client. Fly docs
    describe the header as added by Fly Proxy
    (https://fly.io/docs/networking/request-headers/). Run the DEPLOY.md pre-enable probe
    before relying on client-supplied ``Fly-Client-IP`` being ignored.
    """
    return client_ip_from_headers(request.headers, socket_peer_host(request))


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
            key_func=client_ip,
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
