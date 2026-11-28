"""Pinned uvicorn launch kwargs for the web process (#1633).

``proxy_headers=True`` with ``forwarded_allow_ips=127.0.0.1`` lets loopback peers
trust client ``X-Forwarded-For`` into ``request.client``, which re-opens #1633 off-Fly.
We keep ``proxy_headers=False`` and key limits on the TCP peer (``socket_peer_host``).
``FORWARDED_ALLOW_IPS`` must not widen trust in prod; the launcher pops it.
Fly edge must use ``Fly-Client-IP`` for per-client keys on Fly.
"""

from __future__ import annotations

# ponytail: uvicorn default is 127.0.0.1; env FORWARDED_ALLOW_IPS on Fly overrides — document in DEPLOY.md
UVICORN_FORWARDED_ALLOW_IPS: str = "127.0.0.1"

UVICORN_WEB_KWARGS = {
    "forwarded_allow_ips": UVICORN_FORWARDED_ALLOW_IPS,
    "proxy_headers": False,
}
