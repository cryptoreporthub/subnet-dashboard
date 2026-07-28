"""Cached + bounded readiness builds — keep /api/ops/readiness off the event-loop wedge."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Any, Dict, Optional

_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}
_CACHE_LOCK = threading.Lock()
_BUILD_LOCK = threading.Lock()

TTL = float(os.environ.get("READINESS_CACHE_SECONDS", "45"))
BUILD_TIMEOUT = float(os.environ.get("READINESS_BUILD_TIMEOUT_SECONDS", "4"))


def _stale_copy() -> Optional[Dict[str, Any]]:
    with _CACHE_LOCK:
        payload = _CACHE.get("payload")
        return dict(payload) if isinstance(payload, dict) else None


def _store(payload: Dict[str, Any]) -> Dict[str, Any]:
    with _CACHE_LOCK:
        _CACHE["at"] = time.time()
        _CACHE["payload"] = payload
    return payload


def _build_blocking(*, force: bool = False) -> Dict[str, Any]:
    if not _BUILD_LOCK.acquire(blocking=False):
        stale = _stale_copy()
        if stale is not None and not force:
            return stale
        _BUILD_LOCK.acquire(blocking=True)
    try:
        if not force:
            stale = _stale_copy()
            if stale is not None:
                with _CACHE_LOCK:
                    age = time.time() - float(_CACHE.get("at") or 0)
                if age < TTL:
                    return stale
        from internal.ops.readiness import build_readiness_report

        return _store(build_readiness_report())
    finally:
        _BUILD_LOCK.release()


async def get_readiness_report(*, force: bool = False) -> Dict[str, Any]:
    """Return cached readiness when fresh; otherwise build in a worker thread."""
    now = time.time()
    if not force:
        with _CACHE_LOCK:
            payload = _CACHE.get("payload")
            age = now - float(_CACHE.get("at") or 0)
            if isinstance(payload, dict) and age < TTL:
                return {**payload, "cached": True, "cache_age_seconds": round(age, 1)}

    try:
        payload = await asyncio.wait_for(
            asyncio.to_thread(lambda: _build_blocking(force=force)),
            timeout=BUILD_TIMEOUT + 0.5,
        )
        return {**payload, "cached": False}
    except asyncio.TimeoutError:
        from internal.ops.readiness import build_liveness_report

        lite = build_liveness_report()
        stale = _stale_copy()
        out: Dict[str, Any] = {
            **lite,
            "status": "busy",
            "ready": False,
            "cached": False,
            "issues": ["readiness_build_timeout"],
            "next_levers": ["retry_after_worker_idle"],
        }
        if stale is not None:
            out["stale_report"] = stale
        return out
