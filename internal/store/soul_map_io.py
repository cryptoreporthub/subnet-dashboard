"""Thread-safe read-modify-write gateway for data/soul_map.json."""

from __future__ import annotations

import copy
import fcntl
import json
import logging
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

logger = logging.getLogger(__name__)

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


@contextmanager
def _locked_soul_map_file(path: str, timeout_seconds: float = 5.0) -> Iterator[None]:
    """Cross-process lock for soul_map read-modify-replace."""
    lock_path = path + ".lock"
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        deadline = time.monotonic() + timeout_seconds
        acquired = False
        while time.monotonic() < deadline:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, OSError):
                time.sleep(0.01)
        if not acquired:
            raise TimeoutError(
                f"Timed out after {timeout_seconds}s waiting for {lock_path}"
            )
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


_READER_LOCK_WAIT_SECONDS = 0.05


@contextmanager
def _file_and_reader_locks(path: str) -> Iterator[None]:
    reader = _lock_for(path)
    while True:
        acquired_reader = False
        try:
            with _locked_soul_map_file(path):
                acquired_reader = reader.acquire(timeout=_READER_LOCK_WAIT_SECONDS)
                if acquired_reader:
                    try:
                        yield
                    finally:
                        reader.release()
                    return
        except TimeoutError:
            # 5s file-lock poll expired. Retry on this loop until the holder releases.
            if acquired_reader:
                raise
        time.sleep(_READER_LOCK_WAIT_SECONDS)


def _read_blob_for_write(path: str) -> Dict[str, Any]:
    """Read the blob a write is about to replace. Only a missing file counts as empty."""
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError("soul map top level is not a JSON object")
    return data


def _read_blob(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _cache_get_fresh(path: str, now: float) -> Optional[Dict[str, Any]]:
    """Return the cached blob for `path` if younger than `_CACHE_TTL`, else None.

    Returns the live cache entry (not a copy). Caller MUST hold the lock for
    `path` and MUST NOT mutate the returned dict unless it deep-copies first.
    """
    entry = _cache.get(path)
    if entry is None:
        return None
    cached_at, blob = entry
    if now - cached_at < _CACHE_TTL:
        return blob
    return None


def _cache_put(path: str, blob: Dict[str, Any], now: float) -> None:
    """Store a deep copy of `blob` in the cache for `path` with timestamp `now`.
    Caller MUST hold the lock for `path` before calling this."""
    _cache[path] = (now, copy.deepcopy(blob))


def read_soul_map(path: Optional[str] = None, *, copy_blob: bool = True) -> Dict[str, Any]:
    """Thread-safe read of the whole soul_map blob.

    Resolves path=None to weights.SOUL_MAP_PATH (lazy import).
    Returns {} on missing/invalid/non-dict; never raises.
    May return a cached copy up to SOUL_MAP_CACHE_TTL seconds old; writes made
    through write_soul_map() are always immediately visible regardless of the cache.

    copy_blob=True (default): return an independent deep copy (safe to mutate).
    copy_blob=False: return the cached blob for read-only use. Scoring hot paths
    must use this — deepcopy-per-subnet of soul_map starved Fly's single worker
    (simivision/judges hung while deepcopy ran ~280× per universe score).
    """
    resolved = _resolve_path(path)
    with _lock_for(resolved):
        now = time.monotonic()
        hit = _cache_get_fresh(resolved, now)
        if hit is not None:
            return copy.deepcopy(hit) if copy_blob else hit
        blob = _read_blob(resolved)
        _cache_put(resolved, blob, now)
        cached = _cache[resolved][1]
        return copy.deepcopy(cached) if copy_blob else cached


def write_soul_map(
    mutator: Callable[[Dict[str, Any]], None],
    path: Optional[str] = None,
) -> Dict[str, Any]:
    """Thread-safe read-modify-write. Returns the blob that write_soul_map_committed reports."""
    return write_soul_map_committed(mutator, path)[1]


def write_soul_map_committed(
    mutator: Callable[[Dict[str, Any]], None],
    path: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Thread-safe read-modify-write under a per-path lock.

    Resolves path=None to weights.SOUL_MAP_PATH (lazy import).
    Acquires a lock for this path, reads current blob ({} if missing/bad),
    calls mutator(blob) which mutates the dict in place, then atomically
    writes it back. Exceptions from mutator propagate. Never raises from I/O.
    Returns (committed, blob):
      - (True, committed blob) when the write reached disk. The blob includes every
        writer's changes, so a caller can sync its memory to it.
      - (False, pre-mutation blob) when the disk write failed.
      - (False, {}) when the existing file could not be read; the file is left unchanged.
    On a disk-write failure, logs a warning without updating the cache. Successful writes
    immediately refresh the in-process cache, so a write followed by a read in the same
    process always sees the new data.
    """
    resolved = _resolve_path(path)
    with _lock_for(resolved + ".writers"):
        with _file_and_reader_locks(resolved):
            # Read disk, never the cache: another process may have written the file since
            # this process cached it. The file lock is held, so this read-modify-write is safe.
            try:
                blob = _read_blob_for_write(resolved)
            except Exception as exc:
                # Replacing a file we could not read would destroy its contents. Leave it as is.
                logger.warning(
                    "soul_map read failed before write path=%s error_type=%s error=%s",
                    resolved,
                    type(exc).__name__,
                    exc,
                    extra={
                        "event": "soul_map_persistence_failed",
                        "path": resolved,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                return False, {}
            prior = copy.deepcopy(blob)
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
                temp_path = ""
            except Exception as exc:
                logger.warning(
                    "soul_map persistence failed path=%s error_type=%s error=%s",
                    resolved,
                    type(exc).__name__,
                    exc,
                    extra={
                        "event": "soul_map_persistence_failed",
                        "path": resolved,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                return False, prior
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except Exception:
                        pass
            # The disk write has landed. A cache failure here must not report the write as failed,
            # so drop the cache entry and let the next read reload from disk.
            try:
                _cache_put(resolved, blob, time.monotonic())
            except Exception as exc:
                _cache.pop(resolved, None)
                logger.warning(
                    "soul_map cache refresh failed after commit path=%s error_type=%s error=%s",
                    resolved,
                    type(exc).__name__,
                    exc,
                )
            return True, blob
