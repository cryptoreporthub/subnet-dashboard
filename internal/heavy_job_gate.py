"""Serialize CPU-heavy background jobs on a single Fly VM (pump / snapshot / resolver)."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

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
        holder = _holder or "unknown"
        try:
            logger.info("heavy_job_slot reject name=%s holder=%s", name, holder)
        except Exception:
            pass
        yield False
        return
    started = time.perf_counter()
    try:
        _holder = name
        try:
            logger.info("heavy_job_slot acquire name=%s", name)
        except Exception:
            pass
        yield True
    finally:
        held_ms = (time.perf_counter() - started) * 1000
        release_name = name
        try:
            _lock.release()
            if _holder == release_name:
                _holder = None
        finally:
            try:
                logger.info(
                    "heavy_job_slot release name=%s held_ms=%.1f",
                    release_name,
                    held_ms,
                )
            except Exception:
                pass
