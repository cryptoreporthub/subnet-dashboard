"""Proxy volume-backed GET APIs from web → worker machine (Fly split v2)."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

_PROXY_PREFIXES = ("/api/message-intel", "/api/pump-alerts")


def worker_internal_base() -> str:
    return os.environ.get(
        "WORKER_INTERNAL_URL",
        "http://worker.process.subnet-dashboard.internal:8080",
    ).rstrip("/")


def should_proxy_path(path: str) -> bool:
    from internal.data_volume import needs_worker_volume_proxy

    if not needs_worker_volume_proxy():
        return False
    if path == "/api/pump-alerts":
        return True
    return path.startswith("/api/message-intel")


def fetch_worker_json_sync(path: str, *, timeout: Optional[float] = None) -> Dict[str, Any]:
    """Sync GET for listener_status and other in-process callers."""
    if timeout is None:
        timeout = float(os.environ.get("WORKER_PROXY_TIMEOUT_SECONDS", "10"))
    url = f"{worker_internal_base()}{path}"
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(url, headers={"X-Worker-Proxy": "1"})
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}


async def proxy_get_to_worker(request: Request) -> Response:
    path = request.url.path
    query = request.url.query
    url = f"{worker_internal_base()}{path}"
    if query:
        url = f"{url}?{query}"
    timeout = float(os.environ.get("WORKER_PROXY_TIMEOUT_SECONDS", "12"))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers={"X-Worker-Proxy": "1"})
        media_type = resp.headers.get("content-type") or "application/json"
        return Response(content=resp.content, status_code=resp.status_code, media_type=media_type)
    except Exception as exc:
        logger.warning("worker volume proxy failed %s: %s", path, exc)
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "error": "worker_volume_proxy_failed",
                "path": path,
            },
        )
