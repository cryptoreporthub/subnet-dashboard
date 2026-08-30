"""Passive occupancy capture (Patch D / M7). Observe only — no cancel, no timeout bump.

GIL contention is NOT passively observable here. Check 3 records TMC-lock wait,
fcntl wait, and thread names; naming GIL requires py-spy / faulthandler at M8.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("server")

_LOCK = threading.Lock()
_MAX = 24
_events: List[Dict[str, Any]] = []
_block: List[Dict[str, Any]] = []
_thread_samples: List[Dict[str, Any]] = []
_alive: Dict[int, bool] = {}
_rest_thread_count: Optional[int] = None


def reset() -> None:
    with _LOCK:
        _events.clear()
        _block.clear()
        _thread_samples.clear()
        _alive.clear()
        global _rest_thread_count
        _rest_thread_count = None


def _trim(buf: List[Dict[str, Any]]) -> None:
    del buf[:-_MAX]


def _thread_names() -> List[str]:
    return sorted(t.name for t in threading.enumerate())


def note_rest_baseline() -> int:
    n = threading.active_count()
    with _LOCK:
        global _rest_thread_count
        if _rest_thread_count is None:
            _rest_thread_count = n
        return int(_rest_thread_count)


def note_tick_start(generation: int, *, overlapping: bool) -> None:
    note_rest_baseline()
    names = _thread_names()
    row = {
        "kind": "tick_start",
        "generation": int(generation),
        "overlapping": bool(overlapping),
        "thread_count": len(names),
        "mono": time.monotonic(),
    }
    with _LOCK:
        _alive[int(generation)] = True
        _events.append(row)
        _trim(_events)
        _thread_samples.append({"at": "tick_start", "n": len(names), "names": names[-16:]})
        _trim(_thread_samples)
    if overlapping:
        logger.warning("occupancy_capture retry_spawn overlapping generation=%s", generation)


def note_timeout(generation: int, timeout_s: float, fut: Any) -> None:
    row = {
        "kind": "timeout",
        "generation": int(generation),
        "timeout_s": float(timeout_s),
        "future_running": bool(getattr(fut, "running", lambda: False)()),
        "mono": time.monotonic(),
    }
    with _LOCK:
        _events.append(row)
        _trim(_events)
    logger.warning(
        "occupancy_capture generation_timeout generation=%s timeout_s=%s future_running=%s",
        generation,
        timeout_s,
        row["future_running"],
    )
    for delay in (5.0, 60.0):
        _schedule_survival(int(generation), delay, fut)


def _schedule_survival(generation: int, delay_s: float, fut: Any) -> None:
    def _probe() -> None:
        running = bool(getattr(fut, "running", lambda: False)())
        names = _thread_names()
        work = [n for n in names if "daily-pick" in n]
        with _LOCK:
            _alive[generation] = running or bool(work)
            _events.append(
                {
                    "kind": "survival",
                    "generation": generation,
                    "delay_s": delay_s,
                    "future_running": running,
                    "daily_pick_threads": work,
                    "thread_count": len(names),
                    "survived_past_timeout": running or bool(work),
                }
            )
            _trim(_events)
        logger.warning(
            "occupancy_capture generation_survival generation=%s delay_s=%s "
            "future_running=%s daily_pick_threads=%s",
            generation,
            delay_s,
            running,
            work,
        )

    t = threading.Timer(delay_s, _probe)
    t.daemon = True
    t.start()


def note_block(kind: str, wait_ms: float, held_ms: float = 0.0) -> None:
    row = {
        "kind": kind,
        "wait_ms": round(float(wait_ms), 3),
        "held_ms": round(float(held_ms), 3),
        "mono": time.monotonic(),
    }
    with _LOCK:
        _block.append(row)
        _trim(_block)
    if wait_ms >= 50.0:
        logger.warning("occupancy_capture block %s wait_ms=%.1f held_ms=%.1f", kind, wait_ms, held_ms)


def snapshot() -> Dict[str, Any]:
    names = _thread_names()
    with _LOCK:
        overlap = any(e.get("overlapping") for e in _events if e.get("kind") == "tick_start")
        survived = [
            e for e in _events if e.get("kind") == "survival" and e.get("survived_past_timeout")
        ]
        rest = _rest_thread_count
        return {
            "patch_d": "OPEN",
            "gil": "not_passively_observable",
            "abandoned_block_hypothesis": "unproven",
            "checks": {
                "generation_survival": {
                    "events": list(_events),
                    "any_survived_past_timeout": bool(survived),
                },
                "retry_spawn": {"overlapping_seen": overlap},
                "abandoned_worker_block": {
                    "samples": list(_block),
                    "tmc_lock": [b for b in _block if b.get("kind") == "tmc_lock"],
                    "fcntl": [b for b in _block if b.get("kind") == "fcntl"],
                    "gil": "not_passively_observable — use py-spy/faulthandler at M8",
                },
                "thread_count": {
                    "rest_baseline": rest,
                    "now": len(names),
                    "names_tail": names[-16:],
                    "samples": list(_thread_samples),
                },
            },
        }
