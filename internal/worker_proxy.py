"""Proxy volume-backed GET APIs from web → worker machine (Fly split v2)."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

_LAST_GOOD_BASE: Optional[str] = None
_LAST_PROBE_ERROR: Optional[str] = None


def last_worker_probe_error() -> Optional[str]:
    return _LAST_PROBE_ERROR


def _record_probe_error(exc: BaseException, *, overwrite: bool = True) -> None:
    global _LAST_PROBE_ERROR
    msg = str(exc)[:240]
    if overwrite or not _LAST_PROBE_ERROR:
        _LAST_PROBE_ERROR = msg


def _internal_transport() -> httpx.AsyncHTTPTransport:
    return httpx.AsyncHTTPTransport(local_address="::")


def _requests_json_sync(url: str, *, timeout: float) -> Dict[str, Any]:
    import requests

    resp = requests.get(url, headers={"X-Worker-Proxy": "1"}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}


async def _httpx_get(url: str, *, timeout: float) -> httpx.Response:
    """Try default transport then IPv6 :: bind (Fly 6PN paths differ per machine)."""
    last_exc: Optional[BaseException] = None
    first = True
    for transport in (None, _internal_transport()):
        try:
            client_kw: Dict[str, Any] = {"timeout": timeout}
            if transport is not None:
                client_kw["transport"] = transport
            async with httpx.AsyncClient(**client_kw) as client:
                return await client.get(url, headers={"X-Worker-Proxy": "1"})
        except Exception as exc:
            last_exc = exc
            _record_probe_error(exc, overwrite=first)
            first = False
    if last_exc is not None:
        raise last_exc
    raise OSError("httpx failed")


async def _httpx_post(url: str, *, timeout: float, content: bytes, headers: Dict[str, str]) -> httpx.Response:
    last_exc: Optional[BaseException] = None
    first = True
    hdrs = dict(headers)
    hdrs.setdefault("X-Worker-Proxy", "1")
    for transport in (None, _internal_transport()):
        try:
            client_kw: Dict[str, Any] = {"timeout": timeout}
            if transport is not None:
                client_kw["transport"] = transport
            async with httpx.AsyncClient(**client_kw) as client:
                return await client.post(url, content=content, headers=hdrs)
        except Exception as exc:
            last_exc = exc
            _record_probe_error(exc, overwrite=first)
            first = False
    if last_exc is not None:
        raise last_exc
    raise OSError("httpx post failed")


def _is_web_misroute(data: Dict[str, Any], path: str) -> bool:
    """flycast can hit web — ops/live returns HTTP peer loop instead of file heartbeat."""
    if "/api/ops/" not in path:
        return False
    wp = data.get("worker_peer")
    return isinstance(wp, dict) and wp.get("source") == "http"


def _is_machine_specific_base(base: str) -> bool:
    """6PN literal / per-machine DNS — goes stale when the worker machine is recreated."""
    if base.startswith("http://[fdaa:"):
        return True
    if ".vm." in base and ".internal" in base:
        return True
    return False


def _record_good_base(base: str) -> None:
    global _LAST_GOOD_BASE
    if _is_machine_specific_base(base):
        return
    _LAST_GOOD_BASE = base


def _flycast_opt_in() -> bool:
    return os.environ.get("WORKER_INTERNAL_USE_FLYCAST", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def worker_http_port() -> int:
    try:
        return int(os.environ.get("WORKER_HTTP_PORT", "8081"))
    except ValueError:
        return 8081


def worker_internal_bases() -> List[str]:
    """Ordered URLs for worker HTTP — worker-only port avoids web 8080 collision."""
    app = os.environ.get("FLY_APP_NAME", "subnet-dashboard").strip() or "subnet-dashboard"
    port = worker_http_port()
    flycast_pub = f"http://{app}.flycast:8080"
    flycast_worker = f"http://{app}.flycast:{port}"
    region = os.environ.get("FLY_REGION", "").strip()
    regional = f"http://worker.process.{region}.{app}.internal:{port}" if region else None
    process = f"http://worker.process.{app}.internal:{port}"

    # Stable routes survive worker machine replacement; WORKER_INTERNAL_URL IP does not.
    stable: List[str] = [flycast_worker]
    if regional:
        stable.append(regional)
    stable.append(process)

    bases: List[str] = []
    if _LAST_GOOD_BASE and _LAST_GOOD_BASE in stable:
        bases.append(_LAST_GOOD_BASE)
    for base in stable:
        if base not in bases:
            bases.append(base)

    custom = os.environ.get("WORKER_INTERNAL_URL", "").strip().rstrip("/")
    # ponytail: legacy fly secrets may still set flycast:8080 — ignore unless opted in.
    if custom and (custom != flycast_pub or _flycast_opt_in()):
        if custom not in bases:
            bases.append(custom)
    if _flycast_opt_in() and flycast_pub not in bases:
        bases.append(flycast_pub)
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
    if path == "/api/pump-ladder/state" or path.startswith("/api/pump-ladder/"):
        return True
    if path in (
        "/api/daily-pick",
        "/api/council/weights",
        "/api/learning/health",
        "/api/learning/stats",
        "/api/learning-metrics",
        "/api/ops/evidence",
        "/api/data-freshness",
        "/api/dev-radar",
    ):
        return True
    if path.startswith("/api/message-intel"):
        return True
    # Volume-backed learning ledger + mindmap (GET only — middleware skips POST).
    if path.startswith("/api/mindmap"):
        return True
    if path == "/api/predictions" or path.startswith("/api/predictions/"):
        return True
    return False


def should_proxy_write_path(method: str, path: str) -> bool:
    from internal.data_volume import needs_worker_volume_proxy

    if not needs_worker_volume_proxy():
        return False
    if method != "POST":
        return False
    return path == "/api/pump-ladder/scan" or path.startswith("/api/pump-ladder/")


def fetch_learning_stats_sync(*, timeout: Optional[float] = None) -> Dict[str, Any]:
    """split_v2 web — resolver stats from worker-owned predictions.json."""
    remote = fetch_worker_json_sync("/api/learning/stats", timeout=timeout)
    data = remote.get("data")
    return data if isinstance(data, dict) else {}


async def _fetch_worker_http(path: str, *, query: str = "", timeout: float) -> httpx.Response:
    """GET worker internal HTTP — same AsyncClient path as volume proxy middleware."""
    last_exc: Optional[BaseException] = None
    for base in worker_internal_bases():
        url = f"{base}{path}"
        if query:
            url = f"{url}?{query}"
        try:
            resp = await _httpx_get(url, timeout=timeout)
            if resp.status_code in (404, 502, 503):
                logger.debug("worker HTTP %s status %s", url, resp.status_code)
                last_exc = httpx.HTTPStatusError(
                    f"status {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
                _record_probe_error(last_exc)
                continue
            resp.raise_for_status()
            try:
                data = resp.json()
                if isinstance(data, dict) and _is_web_misroute(data, path):
                    logger.debug("worker HTTP misroute (web) %s", url)
                    last_exc = httpx.HTTPStatusError(
                        "web misroute",
                        request=resp.request,
                        response=resp,
                    )
                    _record_probe_error(last_exc)
                    continue
            except Exception:
                pass
            _record_good_base(base)
            _LAST_PROBE_ERROR = None
            return resp
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            _record_probe_error(exc)
            if exc.response.status_code in (404, 502, 503):
                logger.debug("worker HTTP %s status %s", url, exc.response.status_code)
                continue
            logger.debug("worker HTTP %s failed: %s", url, exc)
        except Exception as exc:
            last_exc = exc
            _record_probe_error(exc)
            logger.debug("worker HTTP %s failed: %s", url, exc)
            try:
                data = _requests_json_sync(url, timeout=timeout)
                if _is_web_misroute(data, path):
                    last_exc = OSError("web misroute (requests)")
                    _record_probe_error(last_exc)
                    continue
                _record_good_base(base)
                _LAST_PROBE_ERROR = None
                return httpx.Response(200, json=data)
            except Exception as req_exc:
                last_exc = req_exc
                _record_probe_error(req_exc, overwrite=False)
                logger.debug("worker requests %s failed: %s", url, req_exc)
    if last_exc is not None:
        raise last_exc
    raise OSError("no worker HTTP base succeeded")


def _run_coro_sync(coro) -> Any:
    """Run async fetch from sync or FastAPI async handlers (no nested asyncio.run)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # ponytail: ops/live is async — asyncio.run there raises; thread pool is the smallest fix.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def fetch_worker_json_sync(path: str, *, timeout: Optional[float] = None) -> Dict[str, Any]:
    """Sync GET for listener_status and worker peer probes (retries alternate bases)."""
    if timeout is None:
        timeout = float(os.environ.get("WORKER_PROXY_TIMEOUT_SECONDS", "12"))

    async def _load() -> Dict[str, Any]:
        resp = await _fetch_worker_http(path, timeout=timeout)
        data = resp.json()
        return data if isinstance(data, dict) else {}

    return _run_coro_sync(_load())


async def proxy_get_to_worker(request: Request) -> Response:
    path = request.url.path
    query = request.url.query
    timeout = float(os.environ.get("WORKER_PROXY_TIMEOUT_SECONDS", "12"))
    try:
        resp = await _fetch_worker_http(path, query=query, timeout=timeout)
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


async def proxy_post_to_worker(request: Request) -> Response:
    path = request.url.path
    query = request.url.query
    timeout = float(os.environ.get("WORKER_PROXY_POST_TIMEOUT_SECONDS", "120"))
    body = await request.body()
    headers = {
        k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")
    }
    last_exc: Optional[BaseException] = None
    for base in worker_internal_bases():
        url = f"{base}{path}"
        if query:
            url = f"{url}?{query}"
        try:
            resp = await _httpx_post(url, timeout=timeout, content=body, headers=headers)
            media_type = resp.headers.get("content-type") or "application/json"
            return Response(content=resp.content, status_code=resp.status_code, media_type=media_type)
        except Exception as exc:
            last_exc = exc
            logger.debug("worker HTTP POST %s failed: %s", url, exc)
    logger.warning("worker volume proxy POST failed %s: %s", path, last_exc)
    return JSONResponse(
        status_code=503,
        content={
            "status": "error",
            "error": "worker_volume_proxy_failed",
            "path": path,
        },
    )
