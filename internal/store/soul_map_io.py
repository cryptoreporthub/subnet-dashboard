"""Thread-safe read-modify-write gateway for data/soul_map.json."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from typing import Any, Callable, Dict, Optional

_locks: Dict[str, threading.Lock] = {}
_meta_lock = threading.Lock()


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


def read_soul_map(path: Optional[str] = None) -> Dict[str, Any]:
    """Thread-safe read of the whole soul_map blob.

    Resolves path=None to weights.SOUL_MAP_PATH (lazy import).
    Returns {} on missing/invalid/non-dict; never raises.
    """
    resolved = _resolve_path(path)
    with _lock_for(resolved):
        return _read_blob(resolved)


def write_soul_map(
    mutator: Callable[[Dict[str, Any]], None],
    path: Optional[str] = None,
) -> Dict[str, Any]:
    """Thread-safe read-modify-write under a per-path lock.

    Resolves path=None to weights.SOUL_MAP_PATH (lazy import).
    Acquires a lock for this path, reads current blob ({} if missing/bad),
    calls mutator(blob) which mutates the dict in place, then atomically
    writes it back. Returns the final blob. Never raises from I/O.
    """
    resolved = _resolve_path(path)
    with _lock_for(resolved):
        blob = _read_blob(resolved)
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
        except Exception:
            pass
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
        return blob
