"""Serialize CPU-heavy background jobs on a single Fly VM (pump / snapshot / resolver)."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator, Optional

_lock = threading.Lock()
_holder: Optional[str] = None


def current_holder() -> Optional[str]:
    return _holder


@contextmanager
def heavy_job_slot(name: str) -> Iterator[bool]:
    """Acquire exclusive heavy-job slot; yield False if another job is running."""
    global _holder
    acquired = _lock.acquire(blocking=False)
    if not acquired:
        yield False
        return
    try:
        _holder = name
        yield True
    finally:
        _holder = None
        _lock.release()
