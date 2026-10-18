"""Per-build cost counters for one score-snapshot build.

Snapshot builds are single-flight, so one active record per process is enough.
When no build is active, ``record`` does nothing, so request-path and standalone
callers pay only a lock acquisition.

Limits: process CPU is process-wide, and RPC and conviction calls made by other
threads during the build window are counted too.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

_lock = threading.Lock()
_active: Optional[Dict[str, Any]] = None


def begin(build_id: str) -> None:
    global _active
    with _lock:
        _active = {
            "build_id": build_id,
            "cpu_start": time.process_time(),
            "wall_start": time.monotonic(),
            "conviction_queries": 0,
            "conviction_query_seconds": 0.0,
            "rpc_calls": 0,
            "rpc_seconds": 0.0,
        }


def record(kind: str, seconds: float) -> None:
    with _lock:
        if _active is None:
            return
        if kind == "conviction":
            _active["conviction_queries"] += 1
            _active["conviction_query_seconds"] += seconds
        elif kind == "rpc":
            _active["rpc_calls"] += 1
            _active["rpc_seconds"] += seconds


def end() -> Dict[str, Any]:
    global _active
    with _lock:
        active, _active = _active, None
    if active is None:
        return {}
    return {
        "build_id": active["build_id"],
        "wall_seconds": round(time.monotonic() - active["wall_start"], 6),
        "process_cpu_seconds": round(time.process_time() - active["cpu_start"], 6),
        "conviction_queries": active["conviction_queries"],
        "conviction_query_seconds": round(active["conviction_query_seconds"], 6),
        "rpc_calls": active["rpc_calls"],
        "rpc_seconds": round(active["rpc_seconds"], 6),
    }
