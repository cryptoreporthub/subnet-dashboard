"""Security response headers (audit P4)."""

from __future__ import annotations

import os

from starlette.requests import Request
from starlette.responses import Response

_DEFAULT_CSP_REPORT_ONLY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "connect-src 'self' https: wss:; "
    "font-src 'self' data:; "
    "frame-ancestors 'self'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def _hsts_enabled() -> bool:
    flag = os.environ.get("ENABLE_HSTS", "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def security_header_items() -> list[tuple[str, str]]:
    """Return (name, value) pairs for security headers."""
    items: list[tuple[str, str]] = [
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
        ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"),
        ("X-Frame-Options", "SAMEORIGIN"),
    ]
    if _hsts_enabled():
        items.append(("Strict-Transport-Security", "max-age=31536000; includeSubDomains"))
    csp = os.environ.get("CONTENT_SECURITY_POLICY", "").strip()
    csp_ro = os.environ.get("CONTENT_SECURITY_POLICY_REPORT_ONLY", _DEFAULT_CSP_REPORT_ONLY).strip()
    if csp:
        items.append(("Content-Security-Policy", csp))
    elif csp_ro:
        items.append(("Content-Security-Policy-Report-Only", csp_ro))
    return items


def apply_security_headers(request: Request, response: Response) -> None:
    """Attach baseline security headers to every response."""
    for name, value in security_header_items():
        response.headers.setdefault(name, value)
