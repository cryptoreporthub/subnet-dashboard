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
_BG_LOCK = threading.Lock()
_BG_STARTED = False

TTL = float(os.environ.get("READINESS_CACHE_SECONDS", "45"))
# Prod builds (feed + loop_health + soul reads) routinely need >4s under load.
BUILD_TIMEOUT = float(os.environ.get("READINESS_BUILD_TIMEOUT_SECONDS", "8"))


class _BuildBusy(Exception):
    """Another readiness build holds the lock; do not block inside wait_for."""


def _stale_copy() -> Optional[Dict[str, Any]]:
    with _CACHE_LOCK:
        payload = _CACHE.get("payload")
        return dict(payload) if isinstance(payload, dict) else None


def _cache_age() -> float:
    with _CACHE_LOCK:
        return time.time() - float(_CACHE.get("at") or 0)


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
        # Never block wait_for callers behind a long in-flight build.
        raise _BuildBusy()
    try:
        if not force:
            stale = _stale_copy()
            if stale is not None:
                age = _cache_age()
                if age < TTL:
                    return stale
        from internal.ops.readiness import build_readiness_report

        return _store(build_readiness_report())
    finally:
        _BUILD_LOCK.release()


def _kick_background_build() -> None:
    """Warm cache after a timeout without cancelling mid-build waiters."""
    global _BG_STARTED
    with _BG_LOCK:
        if _BG_STARTED:
            return
        _BG_STARTED = True

    def _run() -> None:
        global _BG_STARTED
        try:
            _build_blocking(force=True)
        except _BuildBusy:
            pass
        except Exception:
            pass
        finally:
            with _BG_LOCK:
                _BG_STARTED = False

    threading.Thread(target=_run, name="readiness-cache-warm", daemon=True).start()


def _busy_payload(*, stale: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from internal.ops.readiness import build_liveness_report

    if stale is not None:
        issues = list(stale.get("issues") or [])
        advisories = list(stale.get("advisories") or [])
        if "readiness_build_slow" not in issues:
            issues = issues + ["readiness_build_slow"]
        if "readiness_build_slow" not in advisories:
            advisories = advisories + ["readiness_build_slow"]
        return {
            **stale,
            "cached": True,
            "serving_stale": True,
            "cache_age_seconds": round(_cache_age(), 1),
            "issues": issues,
            "blocking_issues": list(stale.get("blocking_issues") or []),
            "advisories": advisories,
        }

    lite = build_liveness_report(probe_worker=False)
    return {
        **lite,
        "status": "busy",
        "ready": False,
        "cached": False,
        "issues": ["readiness_build_timeout"],
        "blocking_issues": ["readiness_build_timeout"],
        "advisories": [],
        "next_levers": ["retry_after_worker_idle"],
    }


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
    except _BuildBusy:
        _kick_background_build()
        return _busy_payload(stale=_stale_copy())
    except asyncio.TimeoutError:
        _kick_background_build()
        return _busy_payload(stale=_stale_copy())
