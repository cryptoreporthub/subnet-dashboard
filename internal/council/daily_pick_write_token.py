"""Generation-token fence for guarded local disk commits (plan §5)."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

daily_pick_write_token_lock = threading.RLock()

_COMMIT_SLOW_SECONDS = 5.0

_state_lock = threading.Lock()
_generation = 0
_revoked = False
_fence_timeout = False
_commit_slow = False
_last_commit_seconds: Optional[float] = None
_schedule_disabled = False


def issue_daily_pick_write_token() -> int:
    global _generation, _revoked, _fence_timeout, _schedule_disabled
    with daily_pick_write_token_lock:
        _generation += 1
        _revoked = False
        _fence_timeout = False
        _schedule_disabled = False
        gen = _generation
    logger.info("daily_pick_write_token issued generation=%s", gen)
    return gen


def revoke_daily_pick_write_token(*, fence_timeout: bool = False, reason: str = "") -> None:
    global _generation, _revoked, _fence_timeout, _schedule_disabled
    with daily_pick_write_token_lock:
        _revoked = True
        _generation += 1
        if fence_timeout:
            _fence_timeout = True
            _schedule_disabled = True
    logger.warning(
        "daily_pick_write_token revoked fence_timeout=%s reason=%s",
        fence_timeout,
        reason or "unspecified",
    )


def daily_pick_write_token_allowed() -> bool:
    with daily_pick_write_token_lock:
        return not _revoked


def is_daily_pick_schedule_disabled() -> bool:
    with _state_lock:
        return _schedule_disabled


def reenable_daily_pick_schedule() -> None:
    global _schedule_disabled, _revoked
    issue_daily_pick_write_token()


def guarded_bounded_commit(commit_fn: Callable[[], None]) -> bool:
    """Validate token then run local atomic commit under lock (§5.1)."""
    global _commit_slow, _last_commit_seconds
    started = time.monotonic()
    with daily_pick_write_token_lock:
        if not daily_pick_write_token_allowed():
            return False
        commit_fn()
    elapsed = time.monotonic() - started
    with _state_lock:
        _last_commit_seconds = elapsed
        if elapsed > _COMMIT_SLOW_SECONDS:
            _commit_slow = True
            logger.warning("daily_pick guarded commit slow: %.2fs", elapsed)
        else:
            logger.info("daily_pick guarded commit: %.3fs", elapsed)
    return True


def health_flags() -> Dict[str, Any]:
    with _state_lock:
        flags: Dict[str, Any] = {}
        if _fence_timeout:
            flags["daily_pick_write_fence_timeout"] = True
        if _commit_slow:
            flags["daily_pick_commit_slow"] = True
        if _last_commit_seconds is not None:
            flags["daily_pick_last_commit_seconds"] = round(_last_commit_seconds, 3)
        if _schedule_disabled:
            flags["daily_pick_schedule_disabled"] = True
        return flags
