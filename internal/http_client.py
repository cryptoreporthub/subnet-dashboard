"""Shared HTTP fetch layer (Phase B2): httpx + tenacity retries + aiocache.

Sync helpers keep legacy call sites working; async helpers + cache serve FastAPI routes.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx
from aiocache import Cache
from aiocache.decorators import cached
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 15.0
_sync_client: Optional[httpx.Client] = None
_async_client: Optional[httpx.AsyncClient] = None

_RETRY = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
    reraise=True,
)


def _sync_http() -> httpx.Client:
    global _sync_client
    if _sync_client is None:
        _sync_client = httpx.Client(timeout=_DEFAULT_TIMEOUT, follow_redirects=True)
    return _sync_client


async def _async_http() -> httpx.AsyncClient:
    global _async_client
    if _async_client is None:
        _async_client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True)
    return _async_client


async def close_async_client() -> None:
    global _async_client
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None


@_RETRY
def sync_get(url: str, *, timeout: Optional[float] = None, **kwargs: Any) -> httpx.Response:
    return _sync_http().get(url, timeout=timeout or _DEFAULT_TIMEOUT, **kwargs)


@_RETRY
def sync_get_json(url: str, *, timeout: Optional[float] = None, **kwargs: Any) -> Any:
    resp = sync_get(url, timeout=timeout, **kwargs)
    resp.raise_for_status()
    return resp.json()


@_RETRY
async def async_get(url: str, *, timeout: Optional[float] = None, **kwargs: Any) -> httpx.Response:
    client = await _async_http()
    return await client.get(url, timeout=timeout or _DEFAULT_TIMEOUT, **kwargs)


@_RETRY
async def async_get_json(url: str, *, timeout: Optional[float] = None, **kwargs: Any) -> Any:
    resp = await async_get(url, timeout=timeout, **kwargs)
    resp.raise_for_status()
    return resp.json()


def _cache_key_builder(func, url: str, *args, **kwargs) -> str:
    return f"http:{url}"


@cached(ttl=60, cache=Cache.MEMORY, key_builder=_cache_key_builder)
async def async_get_json_cached(url: str, *, timeout: Optional[float] = None, **kwargs: Any) -> Any:
    return await async_get_json(url, timeout=timeout, **kwargs)
