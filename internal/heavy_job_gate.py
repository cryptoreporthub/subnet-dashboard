"""Serialize CPU-heavy background jobs on a single Fly VM (pump / snapshot / resolver)."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

_state_lock = threading.Lock()
_held: bool = False
_holder: Optional[str] = None
_holder_token: int = 0


def current_holder() -> Optional[str]:
    with _state_lock:
        return _holder


@contextmanager
def heavy_job_slot(name: str) -> Iterator[bool]:
    """Acquire exclusive heavy-job slot; yield False if another job is running."""
    global _held, _holder, _holder_token
    my_token = 0
    reject_holder: Optional[str] = None
    acquired = False

    with _state_lock:
        if _held:
            reject_holder = _holder
        else:
            _held = True
            _holder_token += 1
            my_token = _holder_token
            _holder = name
            acquired = True

    if not acquired:
        try:
            logger.info(
                "heavy_job_slot reject name=%s holder=%s", name, reject_holder
            )
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
        with _state_lock:
            if _holder_token == my_token:
                _held = False
                _holder = None
        try:
            logger.info(
                "heavy_job_slot release name=%s held_ms=%.1f",
                release_name,
                held_ms,
            )
        except Exception:
            pass
