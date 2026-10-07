"""Serialize CPU-heavy background jobs on a single Fly VM (pump / snapshot / resolver)."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_holder_lock = threading.Lock()
_holder: Optional[str] = None
_holder_token: int = 0


def current_holder() -> Optional[str]:
    with _holder_lock:
        return _holder


def _read_holder_for_reject() -> str:
    """Read holder for reject after slot busy; spin until visible."""
    for _ in range(200):
        with _holder_lock:
            holder = _holder
        if holder is not None:
            return holder
        time.sleep(0.0005)
    with _holder_lock:
        holder = _holder
    return holder if holder is not None else "unknown"


@contextmanager
def heavy_job_slot(name: str) -> Iterator[bool]:
    """Acquire exclusive heavy-job slot; yield False if another job is running."""
    global _holder, _holder_token
    my_token = 0
    with _holder_lock:
        if _holder is not None:
            holder = _holder
            try:
                logger.info("heavy_job_slot reject name=%s holder=%s", name, holder)
            except Exception:
                pass
            yield False
            return
        _holder_token += 1
        my_token = _holder_token
        _holder = name

    if not _lock.acquire(blocking=False):
        with _holder_lock:
            if _holder_token == my_token:
                _holder = None
            holder = _holder
        if holder is None:
            holder = _read_holder_for_reject()
        try:
            logger.info("heavy_job_slot reject name=%s holder=%s", name, holder)
        except Exception:
            pass
        yield False
        return

    started = time.perf_counter()
    try:
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
        finally:
            with _holder_lock:
                if _holder_token == my_token:
                    _holder = None
            try:
                logger.info(
                    "heavy_job_slot release name=%s held_ms=%.1f",
                    release_name,
                    held_ms,
                )
            except Exception:
                pass
