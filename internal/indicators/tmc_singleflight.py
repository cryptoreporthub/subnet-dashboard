"""Single-flight refresh for price_fetcher's TaoMarketCap caches.

Fixes a thundering-herd bug measured on the post-PR1021 parallel pick:
_fetch_tmc_subnets / _fetch_tmc_candles use 60s-TTL module caches with no
lock, so concurrent dpick scoring workers all miss an expired TTL at the
same moment and each fires its own TaoMarketCap request. install_once()
wraps both fetchers so exactly one thread refetches per expiry; peers
block on the lock and then reuse the freshly populated cache.

Callers see unchanged behavior (return shapes, TTLs, exception
propagation). The shared lock also serializes the two distinct TMC
endpoints against each other during refresh, which is acceptable: both
are rate-limited per-IP and the refresh window is short.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Dict, Iterator, Optional

from internal.indicators import price_fetcher as _pf

_tmc_refresh_lock = threading.Lock()
_installed = False
_orig_fetch_subnets = None
_orig_fetch_candles = None
_lock_wait_recorder: ContextVar[Optional[Callable[[float], None]]] = ContextVar(
    "tmc_lock_wait_recorder", default=None
)


@contextmanager
def lock_wait_timing(recorder: Optional[Callable[[float], None]]) -> Iterator[None]:
    """Record TMC refresh-lock wait time for the active resolver cycle."""
    token = _lock_wait_recorder.set(recorder)
    try:
        yield
    finally:
        _lock_wait_recorder.reset(token)


def _wrap(
    fetch: Callable[[int], Any], cache_dict: Dict[str, Any]
) -> Callable[..., Any]:
    """Return a single-flight version of one TMC fetcher."""
    ttl = int(_pf.TMC_CACHE_TTL_SECONDS)

    def wrapped(timeout: int = int(_pf.LIVE_PRICE_TIMEOUT)) -> Any:
        now = time.time()
        data = cache_dict.get("data")
        if data is not None and (now - float(cache_dict.get("cached_at", 0.0))) < ttl:
            return data

        # Expired/cold: exactly one thread refetches while peers wait here;
        # after the lock releases they re-check and reuse the fresh cache.
        wait_started = time.perf_counter()
        with _tmc_refresh_lock:
            recorder = _lock_wait_recorder.get()
            if recorder is not None:
                recorder((time.perf_counter() - wait_started) * 1000)
            data = cache_dict.get("data")
            now = time.time()
            if data is not None and (now - float(cache_dict.get("cached_at", 0.0))) < ttl:
                return data
            return fetch(timeout)

    return wrapped


def install_once() -> None:
    """Idempotently patch price_fetcher's TMC fetchers to single-flight."""
    global _installed, _orig_fetch_subnets, _orig_fetch_candles
    if _installed:
        return
    _orig_fetch_subnets = _pf._fetch_tmc_subnets
    _orig_fetch_candles = _pf._fetch_tmc_candles
    _pf._fetch_tmc_subnets = _wrap(_orig_fetch_subnets, _pf._tmc_subnets_cache)
    _pf._fetch_tmc_candles = _wrap(_orig_fetch_candles, _pf._tmc_candles_cache)
    _installed = True


def uninstall_for_tests() -> None:
    """Restore unwrapped fetchers (test isolation only)."""
    global _installed
    if _orig_fetch_subnets is not None:
        _pf._fetch_tmc_subnets = _orig_fetch_subnets
    if _orig_fetch_candles is not None:
        _pf._fetch_tmc_candles = _orig_fetch_candles
    _installed = False


def prewarm() -> bool:
    """Best-effort warm of both TMC caches before parallel scoring starts.

    Returns True when both caches are warm; never raises.
    """
    ok = True
    try:
        _pf._fetch_tmc_subnets()
    except Exception:
        ok = False
    try:
        _pf._fetch_tmc_candles()
    except Exception:
        ok = False
    return ok
