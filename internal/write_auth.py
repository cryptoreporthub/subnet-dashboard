"""Optional bearer token for mutating API routes (audit P1).

Default-deny: when WRITE_API_TOKEN is set, all POST/PUT/PATCH/DELETE require
the bearer unless the path is on the public-write allowlist (browser UX).
Contract tests and local dev stay open when WRITE_API_TOKEN is unset.
"""

from __future__ import annotations

import hmac
import os
from typing import Optional
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import get_route_path

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Browser UX writes — stay open when token is set so the public UI keeps working.
_PUBLIC_WRITE_EXACT = frozenset(
    {
        "/api/simivision/chat",
        "/api/investigate/ask",
    }
)

_RESOLVE_FALSE = frozenset({"false", "0", "no", "off", "f", "n", ""})


def write_token() -> str:
    return os.environ.get("WRITE_API_TOKEN", "").strip()


def write_auth_enabled() -> bool:
    return bool(write_token())


def _normalize_path(path: str) -> str:
    if path != "/" and path.endswith("/"):
        return path.rstrip("/")
    return path


def _is_public_write(path: str) -> bool:
    """``path`` must already be normalized."""
    return path in _PUBLIC_WRITE_EXACT


def _resolve_query_protected(query: str) -> bool:
    """True when ``resolve`` is present and not a clear false value (case-insensitive)."""
    if not query:
        return False
    parsed = parse_qs(query, keep_blank_values=True)
    if "resolve" not in parsed:
        return False
    for raw in parsed["resolve"]:
        if str(raw).strip().lower() in _RESOLVE_FALSE:
            continue
        return True
    return False


def _path_protected(method: str, path: str, query: str) -> bool:
    """True when this request must present a valid write token."""
    path = _normalize_path(path)
    if method in _WRITE_METHODS:
        return not _is_public_write(path)
    read_method = method if method != "HEAD" else "GET"
    if read_method == "GET" and path == "/api/resolve-predictions":
        return True
    if read_method == "GET" and path == "/api/predictions/resolved":
        return _resolve_query_protected(query)
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
    path = get_route_path(request.scope)
    if not _path_protected(request.method, path, str(request.url.query)):
        return None
    token = _extract_bearer(request) or ""
    expected = write_token()
    try:
        token_ok = hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))
    except (AttributeError, UnicodeError):
        token_ok = False
    if not token_ok:
        return JSONResponse(
            status_code=401,
            content={"status": "error", "error": "write_api_token_required"},
        )
    return None
