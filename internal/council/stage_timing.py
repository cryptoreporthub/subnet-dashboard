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
from typing import Any, Callable, Dict, Iterator, Optional

_local = threading.local()


def timed_stage(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            sink: Optional[Dict[str, float]] = getattr(_local, "sink", None)
            if sink is None:
                return fn(*args, **kwargs)
            started = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                sink[name] = sink.get(name, 0.0) + (time.perf_counter() - started)

        return wrapper

    return decorate


@contextmanager
def collect_stage_seconds() -> Iterator[Dict[str, float]]:
    """Collect stage timings for the calling thread; nesting restores the outer sink."""
    previous = getattr(_local, "sink", None)
    sink: Dict[str, float] = {}
    _local.sink = sink
    try:
        yield sink
    finally:
        _local.sink = previous
