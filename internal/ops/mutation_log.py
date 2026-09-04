"""Patch D writer/lifecycle mutation logs. Instrumentation only — no control-flow changes."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

MUTATION_PREFIX = "patchd_mutation"
LIFECYCLE_PREFIX = "patchd_lifecycle"

PROCESS_BOOT_ID = uuid.uuid4().hex[:12]

_ctx: ContextVar[Optional[dict]] = ContextVar("patchd_mutation_ctx", default=None)


def ts_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def bind_patchd_context(
    *,
    cycle_generation: Any = None,
    resolver_cycle_id: Any = None,
    trigger: Optional[str] = None,
) -> Token:
    current = dict(_ctx.get() or {})
    if cycle_generation is not None:
        current["cycle_generation"] = cycle_generation
    if resolver_cycle_id is not None:
        current["resolver_cycle_id"] = resolver_cycle_id
    if trigger is not None:
        current["trigger"] = trigger
    return _ctx.set(current)


def reset_patchd_context(token: Token) -> None:
    _ctx.reset(token)


def _abandoned_from_timing() -> Optional[bool]:
    try:
        from internal.council.resolver_scheduler import _cycle_timing

        timing = _cycle_timing.get()
        if timing is not None:
            return bool(timing.is_abandoned())
    except Exception:
        return None
    return None


def log_mutation(
    *,
    operation: str,
    path: Any = None,
    writer_function: Optional[str] = None,
    trigger: Optional[str] = None,
    abandoned: Optional[bool] = None,
    cycle_generation: Any = None,
    resolver_cycle_id: Any = None,
    caller: Optional[str] = None,
    prefix: str = MUTATION_PREFIX,
    extra: Optional[dict] = None,
) -> None:
    """Emit one structured info line. Never raises."""
    try:
        ctx = _ctx.get() or {}
        if cycle_generation is None:
            cycle_generation = ctx.get("cycle_generation")
        if resolver_cycle_id is None:
            resolver_cycle_id = ctx.get("resolver_cycle_id")
        if trigger is None:
            trigger = ctx.get("trigger")
        if abandoned is None:
            abandoned = _abandoned_from_timing()
        payload = {
            "abandoned": abandoned,
            "caller": caller,
            "cycle_generation": cycle_generation,
            "operation": operation,
            "path": path,
            "process_boot_id": PROCESS_BOOT_ID,
            "process_generation": os.getpid(),
            "reason": trigger,
            "resolver_cycle_id": resolver_cycle_id,
            "thread_id": threading.get_ident(),
            "thread_name": threading.current_thread().name,
            "trigger": trigger,
            "ts_utc": ts_utc(),
            "writer_function": writer_function,
        }
        if extra:
            payload.update(extra)
        logger.info("%s %s", prefix, json.dumps(payload, default=str, sort_keys=True))
    except Exception:
        pass


def log_lifecycle(event: str, **kwargs: Any) -> None:
    kwargs.setdefault("writer_function", "resolver_scheduler")
    log_mutation(operation=event, prefix=LIFECYCLE_PREFIX, **kwargs)
