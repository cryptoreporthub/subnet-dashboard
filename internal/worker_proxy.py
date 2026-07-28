"""Proxy volume-backed GET APIs from web → worker machine (Fly split v2)."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


def worker_internal_bases() -> List[str]:
    """Ordered URLs for worker HTTP — flycast first when [[services]] worker is declared."""
    app = os.environ.get("FLY_APP_NAME", "subnet-dashboard").strip() or "subnet-dashboard"
    bases: List[str] = []
    custom = os.environ.get("WORKER_INTERNAL_URL", "").strip()
    if custom:
        bases.append(custom.rstrip("/"))
    bases.extend(
        [
            f"http://{app}.flycast:8080",
            f"http://worker.process.{app}.internal:8080",
        ]
    )
    seen: set[str] = set()
    out: List[str] = []
    for base in bases:
        if base not in seen:
            seen.add(base)
            out.append(base)
    return out


def worker_internal_base() -> str:
    return worker_internal_bases()[0]


def should_proxy_path(path: str) -> bool:
    from internal.data_volume import needs_worker_volume_proxy

    if not needs_worker_volume_proxy():
        return False
    if path == "/api/pump-alerts":
        return True
    return path.startswith("/api/message-intel")


def fetch_worker_json_sync(path: str, *, timeout: Optional[float] = None) -> Dict[str, Any]:
    """Sync GET for listener_status and worker peer probes (retries alternate bases)."""
    if timeout is None:
        timeout = float(os.environ.get("WORKER_PROXY_TIMEOUT_SECONDS", "10"))
    last_exc: Optional[BaseException] = None
    for base in worker_internal_bases():
        url = f"{base}{path}"
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, headers={"X-Worker-Proxy": "1"})
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            last_exc = exc
            logger.debug("worker HTTP %s failed: %s", url, exc)
    if last_exc is not None:
        raise last_exc
    return {}


async def proxy_get_to_worker(request: Request) -> Response:
    path = request.url.path
    query = request.url.query
    timeout = float(os.environ.get("WORKER_PROXY_TIMEOUT_SECONDS", "12"))
    last_exc: Optional[BaseException] = None
    for base in worker_internal_bases():
        url = f"{base}{path}"
        if query:
            url = f"{url}?{query}"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, headers={"X-Worker-Proxy": "1"})
            media_type = resp.headers.get("content-type") or "application/json"
            return Response(content=resp.content, status_code=resp.status_code, media_type=media_type)
        except Exception as exc:
            last_exc = exc
            logger.debug("worker volume proxy %s failed: %s", url, exc)
    logger.warning("worker volume proxy failed %s: %s", path, last_exc)
    return JSONResponse(
        status_code=503,
        content={
            "status": "error",
            "error": "worker_volume_proxy_failed",
            "path": path,
        },
    )
