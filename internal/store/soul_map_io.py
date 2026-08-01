"""Thread-safe read-modify-write gateway for data/soul_map.json."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

_locks: Dict[str, threading.Lock] = {}
_meta_lock = threading.Lock()

# path -> (cached_at_monotonic, blob). Same keying as _locks (resolved path str).
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

# Short TTL as a safety net ONLY for a separate `worker` process (internal/worker.py)
# writing to the same file — same-process writes always refresh the cache
# immediately on success (see write_soul_map), so this TTL never causes
# same-process staleness. Matches this repo's existing `SOMETHING_CACHE_TTL`
# env var convention (see internal/council/hourly_pick.py, internal/cockpit/picks_snapshot.py).
_CACHE_TTL = int(os.environ.get("SOUL_MAP_CACHE_TTL", "5"))


def _resolve_path(path: Optional[str]) -> str:
    if path is not None:
        return path
    from internal.council.weights import SOUL_MAP_PATH as _SOUL_MAP_PATH

    return _SOUL_MAP_PATH


def _lock_for(path: str) -> threading.Lock:
    with _meta_lock:
        if path not in _locks:
            _locks[path] = threading.Lock()
        return _locks[path]


def _read_blob(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _cache_get_fresh(path: str, now: float) -> Optional[Dict[str, Any]]:
    """Return a deep copy of the cached blob for `path` if it exists and is
    younger than `_CACHE_TTL` seconds, else None. Caller MUST hold the lock
    for `path` (via _lock_for) before calling this."""
    entry = _cache.get(path)
    if entry is None:
        return None
    cached_at, blob = entry
    if now - cached_at < _CACHE_TTL:
        return copy.deepcopy(blob)
    return None


def _cache_put(path: str, blob: Dict[str, Any], now: float) -> None:
    """Store a deep copy of `blob` in the cache for `path` with timestamp `now`.
    Caller MUST hold the lock for `path` before calling this."""
    _cache[path] = (now, copy.deepcopy(blob))


def read_soul_map(path: Optional[str] = None) -> Dict[str, Any]:
    """Thread-safe read of the whole soul_map blob.

    Resolves path=None to weights.SOUL_MAP_PATH (lazy import).
    Returns {} on missing/invalid/non-dict; never raises.
    May return a cached copy up to SOUL_MAP_CACHE_TTL seconds old; writes made
    through write_soul_map() are always immediately visible regardless of the cache.
    """
    resolved = _resolve_path(path)
    with _lock_for(resolved):
        now = time.monotonic()
        hit = _cache_get_fresh(resolved, now)
        if hit is not None:
            return hit
        blob = _read_blob(resolved)
        _cache_put(resolved, blob, now)
        return copy.deepcopy(blob)


def write_soul_map(
    mutator: Callable[[Dict[str, Any]], None],
    path: Optional[str] = None,
) -> Dict[str, Any]:
    """Thread-safe read-modify-write under a per-path lock.

    Resolves path=None to weights.SOUL_MAP_PATH (lazy import).
    Acquires a lock for this path, reads current blob ({} if missing/bad),
    calls mutator(blob) which mutates the dict in place, then atomically
    writes it back. Returns the final blob. Never raises from I/O.
    Successful writes immediately refresh the in-process cache, so a write
    followed by a read in the same process always sees the new data.
    """
    resolved = _resolve_path(path)
    with _lock_for(resolved):
        now = time.monotonic()
        cached = _cache_get_fresh(resolved, now)
        blob = cached if cached is not None else _read_blob(resolved)
        mutator(blob)
        temp_path = ""
        try:
            os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
            fd, temp_path = tempfile.mkstemp(
                dir=os.path.dirname(resolved) or ".", suffix=".tmp"
            )
            with os.fdopen(fd, "w") as f:
                json.dump(blob, f, indent=2)
            os.replace(temp_path, resolved)
            _cache_put(resolved, blob, time.monotonic())
            temp_path = ""
        except Exception:
            pass
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
        return blob
