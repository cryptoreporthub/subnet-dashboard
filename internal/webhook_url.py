"""Webhook URL validation — block obvious SSRF targets (audit P1)."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


def validate_webhook_url(url: str) -> str:
    """Require HTTPS and reject literal private/loopback hosts."""
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("webhook url must use https")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("webhook url missing host")
    blocked = {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "metadata.google.internal",
        "metadata",
    }
    if host in blocked or host.endswith(".local") or host.endswith(".internal"):
        raise ValueError("webhook host not allowed")
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise ValueError("webhook host not allowed")
    except ValueError as exc:
        if "webhook host" in str(exc):
            raise
    if parsed.username or parsed.password:
        raise ValueError("webhook url must not include credentials")
    return url
