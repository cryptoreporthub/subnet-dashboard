"""Optional bearer token for mutating API routes (audit P1).

Default-deny: when WRITE_API_TOKEN is set, all POST/PUT/PATCH/DELETE require
the bearer unless the path is on the public-write allowlist (browser UX).
Contract tests and local dev stay open when WRITE_API_TOKEN is unset.
"""

from __future__ import annotations

import hmac
import os
from typing import Optional

from starlette.requests import Request
from starlette.responses import JSONResponse

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Browser UX writes — stay open when token is set so the public UI keeps working.
_PUBLIC_WRITE_EXACT = frozenset(
    {
        "/api/simivision/chat",
        "/api/investigate/ask",
        "/api/feedback",
        "/api/mindmap/feedback",
    }
)
_PUBLIC_WRITE_PREFIXES: tuple[str, ...] = ()


def write_token() -> str:
    return os.environ.get("WRITE_API_TOKEN", "").strip()


def write_auth_enabled() -> bool:
    return bool(write_token())


def _is_public_write(path: str) -> bool:
    return path in _PUBLIC_WRITE_EXACT or any(path.startswith(p) for p in _PUBLIC_WRITE_PREFIXES)


def _path_protected(method: str, path: str, query: str) -> bool:
    """True when this request must present a valid write token."""
    if method in _WRITE_METHODS:
        return not _is_public_write(path)
    if method == "GET" and path == "/api/predictions/resolved":
        q = (query or "").lower()
        return "resolve=true" in q or "resolve=1" in q or "resolve=yes" in q
    return False


def _extract_bearer(request: Request) -> Optional[str]:
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-write-api-token", "").strip() or None


def check_write_auth(request: Request) -> Optional[JSONResponse]:
    """Return 401 JSON when token required and missing/wrong."""
    if not write_auth_enabled():
        return None
    path = request.url.path
    if not _path_protected(request.method, path, str(request.url.query)):
        return None
    token = _extract_bearer(request) or ""
    expected = write_token()
    if not token or not hmac.compare_digest(token, expected):
        return JSONResponse(
            status_code=401,
            content={"status": "error", "error": "write_api_token_required"},
        )
    return None
