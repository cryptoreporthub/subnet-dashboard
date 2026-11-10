"""Thread-safe read-modify-write gateway for data/soul_map.json."""

from __future__ import annotations

import copy
import enum
import fcntl
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, Literal, Optional, Tuple

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

_SOUL_MAP_LOCK_DEADLINE_SECONDS = 5.0
_SIDECAR_CAP = 3
_SIDECAR_HASH_BYTES = 65536

_read_log_guard: Dict[str, float] = {}


class WriteOutcome(enum.Enum):
    APPLIED = "applied"
    DECLINED = "declined"
    REPLACE_FAILED = "replace_failed"
    OWNERSHIP_UNKNOWN = "ownership_unknown"
    UNREADABLE_BLOB = "unreadable_blob"
    LOCK_WAIT_FAILED = "lock_wait_failed"
    READ_FAILED = "read_failed"

    def __bool__(self) -> bool:
        raise TypeError("compare WriteOutcome explicitly, never use it as a boolean")


@dataclass(frozen=True)
class WriteResult:
    outcome: WriteOutcome
    blob: Optional[Dict[str, Any]] = None
    detail: str = ""

    @property
    def committed(self) -> bool:
        return self.outcome is WriteOutcome.APPLIED


@dataclass(frozen=True)
class BlobRead:
    kind: Literal["missing", "loaded", "unreadable", "transient"]
    blob: Optional[Dict[str, Any]]
    error: str = ""


class StateUnreadable(Exception):
    """Soul-map or auxiliary JSON could not be read for cycle work."""

    def __init__(self, kind: str, path: str, *, error: str = "") -> None:
        super().__init__(f"{kind} read failed for {path}: {error}")
        self.kind = kind
        self.path = path
        self.error = error


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


def read_blob_checked(path: str) -> BlobRead:
    """Classify on-disk JSON once at the file boundary."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        return BlobRead("missing", {})
    except UnicodeDecodeError:
        return BlobRead("unreadable", None, error="encoding")
    except (OSError, MemoryError) as exc:
        return BlobRead("transient", None, error=str(exc))
    except Exception as exc:
        return BlobRead("transient", None, error=str(exc))

    if not raw.strip():
        return BlobRead("unreadable", None, error="empty")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return BlobRead("unreadable", None, error="parse")
    except UnicodeDecodeError:
        return BlobRead("unreadable", None, error="parse")
    except (OSError, MemoryError) as exc:
        return BlobRead("transient", None, error=str(exc))

    if not isinstance(data, dict):
        return BlobRead("unreadable", None, error="not_dict")
    return BlobRead("loaded", data)


def _read_blob(path: str) -> Dict[str, Any]:
    """Legacy disk read for callers not yet on read_blob_checked."""
    checked = read_blob_checked(path)
    if checked.kind == "missing":
        return {}
    if checked.kind == "loaded" and checked.blob is not None:
        return checked.blob
    return {}


def _log_read_once(path: str, kind: str, message: str) -> bool:
    key = f"{path}:{kind}"
    now = time.monotonic()
    last = _read_log_guard.get(key, 0.0)
    if now - last < 60.0:
        return False
    _read_log_guard[key] = now
    logger.warning("%s", message)
    return True


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


def _sidecar_paths(path: str) -> list[str]:
    directory = os.path.dirname(path) or "."
    base = os.path.basename(path)
    prefix = base + ".corrupt-"
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    return [os.path.join(directory, n) for n in names if n.startswith(prefix)]


def _quarantine_corrupt(path: str) -> str:
    """Copy unreadable bytes to a content-hash sidecar; never mutates the original."""
    try:
        sidecars = _sidecar_paths(path)
        if len(sidecars) >= _SIDECAR_CAP:
            return "sidecar=capped"

        digest = hashlib.sha256()
        size = 0
        with open(path, "rb") as src:
            while True:
                chunk = src.read(_SIDECAR_HASH_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
        digest_hex = digest.hexdigest()
        name = f"{os.path.basename(path)}.corrupt-{digest_hex[:16]}"
        directory = os.path.dirname(path) or "."
        dest = os.path.join(directory, name)
        if os.path.exists(dest):
            return f"sidecar={name}"

        try:
            st = os.statvfs(directory)
            free = st.f_bavail * st.f_frsize
            if free < size * 2:
                return "sidecar=copy_failed"
        except (OSError, AttributeError):
            pass

        fd, temp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as out, open(path, "rb") as src:
                while True:
                    chunk = src.read(_SIDECAR_HASH_BYTES)
                    if not chunk:
                        break
                    out.write(chunk)
            if os.path.getsize(temp_path) != size:
                os.unlink(temp_path)
                return "sidecar=copy_failed"
            os.replace(temp_path, dest)
            return f"sidecar={name}"
        except OSError:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            return "sidecar=copy_failed"
    except OSError:
        return "sidecar=copy_failed"


def _canonical_blob_json(blob: Dict[str, Any]) -> str:
    return json.dumps(blob, sort_keys=True, separators=(",", ":"))


@contextmanager
def _acquire_write_locks(path: str, deadline: float) -> Iterator[None]:
    """One deadline for .writers, flock, and reader mutex."""
    writers = _lock_for(path + ".writers")
    reader = _lock_for(path)
    writers_acquired = False
    reader_acquired = False
    flock_released = False
    lock_path = path + ".lock"
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    lock_file = open(lock_path, "a+", encoding="utf-8")
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not writers.acquire(timeout=max(0.0, remaining)):
            raise TimeoutError(f"Timed out waiting for writers lock on {path}")
        writers_acquired = True

        while time.monotonic() < deadline:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                time.sleep(0.01)
        else:
            raise TimeoutError(f"Timed out waiting for flock on {lock_path}")

        remaining = deadline - time.monotonic()
        if remaining <= 0 or not reader.acquire(timeout=max(0.0, remaining)):
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            flock_released = True
            raise TimeoutError(f"Timed out waiting for reader lock on {path}")
        reader_acquired = True
        try:
            yield
        finally:
            if reader_acquired:
                reader.release()
            if not flock_released:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()
        if writers_acquired:
            writers.release()


def _cache_get_fresh(path: str, now: float) -> Optional[Dict[str, Any]]:
    """Return the cached blob for `path` if younger than `_CACHE_TTL`, else None."""
    entry = _cache.get(path)
    if entry is None:
        return None
    cached_at, blob = entry
    if now - cached_at < _CACHE_TTL:
        return blob
    return None


def _cache_put(path: str, blob: Dict[str, Any], now: float) -> None:
    """Store a deep copy of `blob` in the cache for `path` with timestamp `now`."""
    _cache[path] = (now, copy.deepcopy(blob))


def read_soul_map(path: Optional[str] = None, *, copy_blob: bool = True) -> Dict[str, Any]:
    """Thread-safe read of the whole soul_map blob.

    Returns {} on missing/invalid/non-dict or transient read failure; never raises.
  Unreadable/transient results are not cached.
    """
    resolved = _resolve_path(path)
    with _lock_for(resolved):
        now = time.monotonic()
        hit = _cache_get_fresh(resolved, now)
        if hit is not None:
            return copy.deepcopy(hit) if copy_blob else hit

        checked = read_blob_checked(resolved)
        if checked.kind == "loaded" and checked.blob is not None:
            _cache_put(resolved, checked.blob, now)
            cached = _cache[resolved][1]
            return copy.deepcopy(cached) if copy_blob else cached
        if checked.kind == "missing":
            empty: Dict[str, Any] = {}
            _cache_put(resolved, empty, now)
            return copy.deepcopy(empty) if copy_blob else empty

        msg = (
            f"soul_map read classified as {checked.kind} path={resolved} error={checked.error}"
        )
        _log_read_once(resolved, checked.kind, msg)
        return {}


def write_soul_map(
    mutator: Callable[[Dict[str, Any]], None],
    path: Optional[str] = None,
    *,
    raise_on_lock_timeout: bool = True,
    pre_replace: Optional[Callable[[], None]] = None,
) -> WriteResult:
    """Thread-safe read-modify-write under per-path locks with typed outcomes."""
    resolved = _resolve_path(path)
    deadline = time.monotonic() + _SOUL_MAP_LOCK_DEADLINE_SECONDS
    mutator_timeout = False
    try:
        with _acquire_write_locks(resolved, deadline):
            checked = read_blob_checked(resolved)
            if checked.kind == "transient":
                return WriteResult(
                    WriteOutcome.READ_FAILED,
                    None,
                    detail=checked.error or "read_failed",
                )
            if checked.kind == "unreadable":
                detail = _quarantine_corrupt(resolved)
                return WriteResult(WriteOutcome.UNREADABLE_BLOB, None, detail=detail)

            assert checked.blob is not None
            blob = copy.deepcopy(checked.blob)
            prior = copy.deepcopy(blob)
            try:
                mutator(blob)
            except TimeoutError:
                mutator_timeout = True
                raise

            if _canonical_blob_json(blob) == _canonical_blob_json(prior):
                return WriteResult(WriteOutcome.DECLINED, blob)

            temp_path = ""
            try:
                os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
                fd, temp_path = tempfile.mkstemp(
                    dir=os.path.dirname(resolved) or ".", suffix=".tmp"
                )
                with os.fdopen(fd, "w") as f:
                    json.dump(blob, f, indent=2)
                if pre_replace is not None:
                    pre_replace()
                os.replace(temp_path, resolved)
                temp_path = ""
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
                return WriteResult(WriteOutcome.APPLIED, blob)
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
                return WriteResult(
                    WriteOutcome.REPLACE_FAILED,
                    prior,
                    detail=str(exc),
                )
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
    except TimeoutError as exc:
        if mutator_timeout:
            raise
        logger.warning(
            "soul_map lock wait timed out path=%s error=%s",
            resolved,
            exc,
            extra={
                "event": "soul_map_lock_wait_timeout",
                "path": resolved,
                "error": str(exc),
            },
        )
        if raise_on_lock_timeout:
            raise
        return WriteResult(WriteOutcome.LOCK_WAIT_FAILED, None, detail=str(exc))


def write_soul_map_committed(
    mutator: Callable[[Dict[str, Any]], None],
    path: Optional[str] = None,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Return ``(committed, blob)``; ``blob`` is ``None`` unless applied or declined."""
    out = write_soul_map(mutator, path, raise_on_lock_timeout=False)
    blob = out.blob if out.outcome in (
        WriteOutcome.APPLIED,
        WriteOutcome.DECLINED,
        WriteOutcome.REPLACE_FAILED,
    ) else None
    return out.committed, blob
