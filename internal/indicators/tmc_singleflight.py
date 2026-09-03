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
from typing import Any, Callable, Dict

from internal.indicators import price_fetcher as _pf

_tmc_refresh_lock = threading.Lock()
_installed = False
_orig_fetch_subnets = None
_orig_fetch_candles = None


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
        t0 = time.monotonic()
        _tmc_refresh_lock.acquire()
        wait_ms = (time.monotonic() - t0) * 1000.0
        held0 = time.monotonic()
        try:
            data = cache_dict.get("data")
            now = time.time()
            if data is not None and (now - float(cache_dict.get("cached_at", 0.0))) < ttl:
                return data
            return fetch(timeout)
        finally:
            held_ms = (time.monotonic() - held0) * 1000.0
            _tmc_refresh_lock.release()
            try:
                from internal.council.occupancy_capture import note_block

                note_block("tmc_lock", wait_ms, held_ms)
            except Exception:
                pass

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
