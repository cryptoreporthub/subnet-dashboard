"""Stage timing for daily pick scheduler profiling (prod + local)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def timing_enabled() -> bool:
    raw = os.environ.get("DAILY_PICK_STAGE_TIMING", "on")
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


class StageTimer:
    """Context manager — ``timer.ms`` set on exit."""

    __slots__ = ("label", "ms", "_t0")

    def __init__(self, label: str) -> None:
        self.label = label
        self.ms = 0.0
        self._t0 = 0.0

    def __enter__(self) -> "StageTimer":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.ms = (time.perf_counter() - self._t0) * 1000


def log_stage_summary(
    prefix: str,
    stages: Dict[str, float],
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    if not timing_enabled():
        return
    parts = " ".join(f"{k}={int(v)}ms" for k, v in stages.items())
    tail = ""
    if extra:
        tail = " " + " ".join(f"{k}={v}" for k, v in extra.items())
    logger.warning("%s %s%s", prefix, parts, tail)
