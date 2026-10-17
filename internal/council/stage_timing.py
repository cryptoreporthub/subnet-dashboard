"""Per-stage wall-clock timing for subnet scoring, collected only when a collector is active.

The score snapshot reports ``day_scoring_seconds`` as one number; on prod it is ~1.3 s per
subnet while the same work takes ~3 ms locally, and the cause is not visible. Decorating the
stage functions and collecting around each ``score_subnet_for_day`` call lets the snapshot's
public ``coverage.timing`` block say where the time goes.
"""

from __future__ import annotations

import functools
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional

_local = threading.local()


def timed_stage(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Record the stage's EXCLUSIVE time: time spent in nested timed stages is charged to them,
    so stage seconds never sum to more than the wall time."""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            sink: Optional[Dict[str, float]] = getattr(_local, "sink", None)
            if sink is None:
                return fn(*args, **kwargs)
            stack: List[float] = _local.stack
            stack.append(0.0)  # time spent in nested timed stages
            started = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - started
                nested = stack.pop()
                sink[name] = sink.get(name, 0.0) + max(0.0, elapsed - nested)
                if stack:
                    stack[-1] += elapsed

        return wrapper

    return decorate


@contextmanager
def collect_stage_seconds() -> Iterator[Dict[str, float]]:
    """Collect stage timings for the calling thread; nesting restores the outer sink."""
    previous_sink = getattr(_local, "sink", None)
    previous_stack = getattr(_local, "stack", None)
    sink: Dict[str, float] = {}
    _local.sink = sink
    _local.stack = []
    try:
        yield sink
    finally:
        _local.sink = previous_sink
        _local.stack = previous_stack
