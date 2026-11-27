"""Pinned uvicorn launch kwargs for the web process (#1633).

``FORWARDED_ALLOW_IPS='*'`` lets clients forge ``X-Forwarded-For``; slowapi's
``get_remote_address`` (used when ``Fly-Client-IP`` is absent on Fly) would then
trust spoofed hops. Pin to loopback-only so only the local reverse proxy may set
forwarded headers. Fly edge must use ``Fly-Client-IP`` for per-client keys.
"""

from __future__ import annotations

# ponytail: uvicorn default is 127.0.0.1; env FORWARDED_ALLOW_IPS on Fly overrides — document in DEPLOY.md
UVICORN_FORWARDED_ALLOW_IPS: str = "127.0.0.1"

UVICORN_WEB_KWARGS = {
    "forwarded_allow_ips": UVICORN_FORWARDED_ALLOW_IPS,
    "proxy_headers": True,
}