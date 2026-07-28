"""Optional bearer token for mutating API routes (audit P1)."""

from __future__ import annotations

import os
from typing import Optional

from starlette.requests import Request
from starlette.responses import JSONResponse

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Contract tests and local dev stay open when WRITE_API_TOKEN is unset.
_PROTECTED_EXACT = frozenset(
    {
        "/api/message-intel/ingest",
        "/api/alerts/subscribe",
        "/api/learning/rebalance-weights",
        "/api/scenario-memory",
        "/api/whales/events",
        "/api/ruggers/events",
        "/api/trace/record",
        "/api/learning/pump-lead/recover",
        "/api/learning/pump-lead/train",
        "/api/conviction-alerts/notify",
        "/api/calibration/retrain",
    }
)
_PROTECTED_PREFIXES = (
    "/api/whales/scan",
    "/api/ruggers/scan",
    "/api/pump-ladder/scan",
)


def write_token() -> str:
    return os.environ.get("WRITE_API_TOKEN", "").strip()


def write_auth_enabled() -> bool:
    return bool(write_token())


def _path_protected(method: str, path: str, query: str) -> bool:
    if method in _WRITE_METHODS and (path in _PROTECTED_EXACT or any(path.startswith(p) for p in _PROTECTED_PREFIXES)):
        return True
    if method == "GET" and path == "/api/predictions/resolved":
        q = (query or "").lower()
        return "resolve=true" in q or "resolve=1" in q or "resolve=yes" in q
    if method == "PUT" and path == "/api/watchlist":
        return True
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
    token = _extract_bearer(request)
    if token != write_token():
        return JSONResponse(
            status_code=401,
            content={"status": "error", "error": "write_api_token_required"},
        )
    return None
