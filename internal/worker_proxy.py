"""Proxy volume-backed GET APIs from web → worker machine (Fly split v2)."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

_LAST_GOOD_BASE: Optional[str] = None


def _record_good_base(base: str) -> None:
    global _LAST_GOOD_BASE
    _LAST_GOOD_BASE = base


def _is_web_misroute(data: Dict[str, Any], path: str) -> bool:
    """flycast can hit web — ops/live returns HTTP peer loop instead of file heartbeat."""
    if "/api/ops/" not in path:
        return False
    wp = data.get("worker_peer")
    return isinstance(wp, dict) and wp.get("source") == "http"


def _flycast_opt_in() -> bool:
    return os.environ.get("WORKER_INTERNAL_USE_FLYCAST", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def worker_internal_bases() -> List[str]:
    """Ordered URLs for worker HTTP — process-group DNS first (avoids flycast hitting web)."""
    app = os.environ.get("FLY_APP_NAME", "subnet-dashboard").strip() or "subnet-dashboard"
    flycast = f"http://{app}.flycast:8080"
    bases: List[str] = []
    if _LAST_GOOD_BASE:
        bases.append(_LAST_GOOD_BASE)
    custom = os.environ.get("WORKER_INTERNAL_URL", "").strip().rstrip("/")
    # ponytail: legacy fly secrets may still set flycast — ignore unless explicitly opted in.
    if custom and (custom != flycast or _flycast_opt_in()):
        bases.append(custom)
    region = os.environ.get("FLY_REGION", "").strip()
    if region:
        bases.append(f"http://worker.process.{region}.{app}.internal:8080")
    bases.append(f"http://worker.process.{app}.internal:8080")
    # flycast load-balances all machines on 8080 — can hit web and break peer probe.
    if _flycast_opt_in():
        bases.append(flycast)
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
            if not isinstance(data, dict):
                data = {}
            if _is_web_misroute(data, path):
                logger.debug("worker HTTP misroute (web) %s", url)
                last_exc = httpx.HTTPStatusError(
                    "web misroute",
                    request=resp.request,
                    response=resp,
                )
                continue
            _record_good_base(base)
            return data
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code in (404, 502, 503):
                logger.debug("worker HTTP %s status %s", url, exc.response.status_code)
                continue
            logger.debug("worker HTTP %s failed: %s", url, exc)
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
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if isinstance(data, dict) and not _is_web_misroute(data, path):
                        _record_good_base(base)
                except Exception:
                    pass
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
