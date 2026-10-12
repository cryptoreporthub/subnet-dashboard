"""Cached + bounded readiness builds — keep /api/ops/readiness off the event-loop wedge."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}
_CACHE_LOCK = threading.Lock()
_BG_LOCK = threading.Lock()
_BG_STARTED = False
_WARM_GENERATION = 0
_WARM_THREAD: Optional[threading.Thread] = None
_REFRESHER_STOP = threading.Event()
_REFRESHER_STARTED = False
_REFRESHER_GENERATION = 0
_REFRESHER_THREAD: Optional[threading.Thread] = None

_BUILD_SLOT_LOCK = threading.Lock()
_BUILD_GENERATION = 0
_ACTIVE_BUILD_GENERATION: Optional[int] = None
_BUILD_STARTED_AT = 0.0
_BUILD_INVOCATIONS = 0

TTL = float(os.environ.get("READINESS_CACHE_SECONDS", "45"))
# Prod builds (feed + loop_health + soul reads) routinely need >4s under load.
BUILD_TIMEOUT = float(os.environ.get("READINESS_BUILD_TIMEOUT_SECONDS", "8"))
MAX_STALE_SECONDS = float(
    os.environ.get("READINESS_MAX_STALE_SECONDS", str(max(TTL * 4, 180.0)))
)
BUILD_WATCHDOG_SECONDS = float(
    os.environ.get("READINESS_BUILD_WATCHDOG_SECONDS", str(BUILD_TIMEOUT + 2.0))
)


class _BuildBusy(Exception):
    """Another readiness build holds the slot; do not block inside wait_for."""


def build_invocation_count() -> int:
    """Tests: count of completed readiness builds (not cache hits)."""
    return _BUILD_INVOCATIONS


def reset_readiness_cache() -> None:
    """Tests/isolation: clear cached readiness, builds, and section in-flight state."""
    global _REFRESHER_GENERATION, _REFRESHER_STARTED, _WARM_GENERATION
    _REFRESHER_GENERATION += 1
    _WARM_GENERATION += 1
    stop_readiness_refresher()
    t = _REFRESHER_THREAD
    if t is not None and t.is_alive():
        t.join(timeout=3.0)
    wt = _WARM_THREAD
    if wt is not None and wt.is_alive():
        wt.join(timeout=3.0)
    global _BUILD_GENERATION, _ACTIVE_BUILD_GENERATION, _BUILD_STARTED_AT, _BUILD_INVOCATIONS
    with _CACHE_LOCK:
        with _BUILD_SLOT_LOCK:
            _CACHE["at"] = 0.0
            _CACHE["payload"] = None
            # ponytail: monotonic fence — do not reset to 0; a slow build that survived reset
            # must not share generation with the next _try_begin_build after reset.
            _BUILD_GENERATION += 1
            _ACTIVE_BUILD_GENERATION = None
            _BUILD_STARTED_AT = 0.0
            _BUILD_INVOCATIONS = 0
    global _BG_STARTED
    _REFRESHER_STARTED = False
    _REFRESHER_STOP.clear()
    with _BG_LOCK:
        _BG_STARTED = False
    try:
        from internal.ops.readiness import reset_readiness_section_state

        reset_readiness_section_state()
    except Exception:
        pass


def readiness_report_age_seconds() -> Optional[float]:
    """Age of cached readiness payload; None when cache empty."""
    with _CACHE_LOCK:
        if not isinstance(_CACHE.get("payload"), dict):
            return None
        return time.time() - float(_CACHE.get("at") or 0)


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
    _touch_metrics_after_store()
    return payload


def _store_if_current(payload: Dict[str, Any], generation: int) -> Dict[str, Any]:
    # Lock order matches reset_readiness_cache: _CACHE_LOCK then _BUILD_SLOT_LOCK.
    with _CACHE_LOCK:
        with _BUILD_SLOT_LOCK:
            if generation != _BUILD_GENERATION:
                logger.info(
                    "readiness build generation %s abandoned (current %s); cache unchanged",
                    generation,
                    _BUILD_GENERATION,
                )
                cached = _CACHE.get("payload")
                stale = dict(cached) if isinstance(cached, dict) else None
                return stale if stale is not None else payload
            _CACHE["at"] = time.time()
            _CACHE["payload"] = payload
    _touch_metrics_after_store()
    return payload


def _touch_metrics_after_store() -> None:
    try:
        from internal.metrics import READINESS_LAST_SUCCESS_UNIX, READINESS_REPORT_AGE_SECONDS

        READINESS_REPORT_AGE_SECONDS.set(0.0)
        READINESS_LAST_SUCCESS_UNIX.set(time.time())
    except Exception:
        pass


def _record_build_failure(reason: str) -> None:
    try:
        from internal.metrics import READINESS_BUILD_FAILURES

        READINESS_BUILD_FAILURES.labels(reason=reason).inc()
    except Exception:
        pass
    logger.warning("readiness background build failed (%s)", reason)


def _apply_stale_verdict(payload: Dict[str, Any], *, cache_age: float) -> Dict[str, Any]:
    """Age is part of the verdict — never report ready=true on ancient data."""
    out = dict(payload)
    issues = list(out.get("issues") or [])
    if cache_age > MAX_STALE_SECONDS and "readiness_stale" not in issues:
        issues.append("readiness_stale")
    out["issues"] = issues
    if cache_age > MAX_STALE_SECONDS:
        out["ready"] = False
        out["status"] = "degraded"
    return out


def _envelope(
    payload: Dict[str, Any],
    *,
    cached: bool,
    cache_age: Optional[float] = None,
    serving_stale: bool = False,
) -> Dict[str, Any]:
    age = cache_age if cache_age is not None else _cache_age()
    out = _apply_stale_verdict(payload, cache_age=age)
    out["cached"] = cached
    out["cache_age_seconds"] = round(age, 1)
    if serving_stale:
        out["serving_stale"] = True
    return out


def _try_begin_build() -> Optional[int]:
    global _BUILD_STARTED_AT, _BUILD_GENERATION, _ACTIVE_BUILD_GENERATION
    now = time.time()
    with _BUILD_SLOT_LOCK:
        if _ACTIVE_BUILD_GENERATION is not None and (now - _BUILD_STARTED_AT) < BUILD_WATCHDOG_SECONDS:
            return None
        if _ACTIVE_BUILD_GENERATION is not None:
            logger.warning(
                "readiness build watchdog: prior build exceeded %.1fs; allowing new build",
                BUILD_WATCHDOG_SECONDS,
            )
        _BUILD_GENERATION += 1
        generation = _BUILD_GENERATION
        _ACTIVE_BUILD_GENERATION = generation
        _BUILD_STARTED_AT = now
        return generation


def _end_build(generation: int) -> None:
    global _ACTIVE_BUILD_GENERATION
    with _BUILD_SLOT_LOCK:
        if _ACTIVE_BUILD_GENERATION == generation:
            _ACTIVE_BUILD_GENERATION = None


def _build_blocking(*, force: bool = False) -> Dict[str, Any]:
    if not force:
        stale = _stale_copy()
        if stale is not None:
            age = _cache_age()
            if age < TTL:
                return stale

    generation = _try_begin_build()
    if generation is None:
        stale = _stale_copy()
        if stale is not None and not force:
            return stale
        raise _BuildBusy()

    try:
        from internal.ops.readiness import build_readiness_report

        global _BUILD_INVOCATIONS
        payload = build_readiness_report()
        _BUILD_INVOCATIONS += 1
        try:
            from internal.metrics import READINESS_BUILDS_TOTAL

            READINESS_BUILDS_TOTAL.inc()
        except Exception:
            pass
        return _store_if_current(payload, generation)
    finally:
        _end_build(generation)


def _kick_background_build() -> None:
    """Warm cache after a timeout without cancelling mid-build waiters."""
    global _BG_STARTED, _WARM_THREAD
    generation = _WARM_GENERATION
    with _BG_LOCK:
        if _BG_STARTED:
            return
        _BG_STARTED = True

    def _run() -> None:
        global _BG_STARTED
        try:
            if generation != _WARM_GENERATION:
                return
            _build_blocking(force=True)
        except _BuildBusy:
            pass
        except Exception as exc:
            _record_build_failure(type(exc).__name__)
        finally:
            with _BG_LOCK:
                if generation == _WARM_GENERATION:
                    _BG_STARTED = False

    _WARM_THREAD = threading.Thread(
        target=_run, name="readiness-cache-warm", daemon=True
    )
    _WARM_THREAD.start()


def _busy_payload(*, stale: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from internal.ops.readiness import build_liveness_report

    if stale is not None:
        issues = list(stale.get("issues") or [])
        if "readiness_build_slow" not in issues:
            issues = issues + ["readiness_build_slow"]
        merged = {**stale, "issues": issues}
        return _envelope(merged, cached=True, serving_stale=True)

    lite = build_liveness_report(probe_worker=False)
    return {
        **lite,
        "status": "busy",
        "ready": False,
        "cached": False,
        "issues": ["readiness_build_timeout"],
        "next_levers": ["retry_after_worker_idle"],
    }


def _empty_read_payload() -> Dict[str, Any]:
    from internal.ops.readiness import build_liveness_report

    lite = build_liveness_report(probe_worker=False)
    return {
        **lite,
        "status": "degraded",
        "ready": False,
        "cached": False,
        "issues": ["readiness_not_warmed"],
        "next_levers": ["wait_for_readiness_refresher"],
    }


def start_readiness_refresher() -> None:
    """Background interval builds — readiness is not computed on the GET path."""
    global _REFRESHER_STARTED, _REFRESHER_THREAD
    if _REFRESHER_STARTED:
        return
    _REFRESHER_STARTED = True
    _REFRESHER_STOP.clear()
    generation = _REFRESHER_GENERATION

    def _loop() -> None:
        global _REFRESHER_STARTED
        # First build soon after boot so monitors do not see readiness_not_warmed long.
        delay = min(5.0, TTL)
        while not _REFRESHER_STOP.wait(delay):
            if generation != _REFRESHER_GENERATION:
                break
            delay = TTL
            try:
                _build_blocking(force=True)
            except _BuildBusy:
                pass
            except Exception as exc:
                _record_build_failure(type(exc).__name__)
        if generation == _REFRESHER_GENERATION:
            _REFRESHER_STARTED = False

    _REFRESHER_THREAD = threading.Thread(
        target=_loop, name="readiness-refresher", daemon=True
    )
    _REFRESHER_THREAD.start()


def stop_readiness_refresher() -> None:
    _REFRESHER_STOP.set()


async def get_readiness_report(*, force: bool = False) -> Dict[str, Any]:
    """Return last stored readiness; only ``force=True`` runs a bounded rebuild."""
    if not force:
        payload = _stale_copy()
        if payload is None:
            _kick_background_build()
            return _empty_read_payload()
        return _envelope(payload, cached=True)

    try:
        payload = await asyncio.wait_for(
            asyncio.to_thread(lambda: _build_blocking(force=True)),
            timeout=BUILD_TIMEOUT + 0.5,
        )
        return _envelope(payload, cached=False, cache_age=0.0)
    except _BuildBusy:
        _kick_background_build()
        stale = _stale_copy()
        if stale is not None:
            return _busy_payload(stale=stale)
        return _busy_payload()
    except asyncio.TimeoutError:
        _kick_background_build()
        stale = _stale_copy()
        if stale is not None:
            return _busy_payload(stale=stale)
        return _busy_payload()
