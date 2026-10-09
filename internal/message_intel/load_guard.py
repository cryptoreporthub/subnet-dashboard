"""Single-flight + short TTL cache for heavy message_intel SQLite loads."""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Dict, Hashable, List, Tuple, TypeVar

T = TypeVar("T")

DEFAULT_TTL = float(os.environ.get("MESSAGE_INTEL_LOAD_CACHE_SECONDS", "30"))
DEFAULT_WAIT = float(os.environ.get("MESSAGE_INTEL_LOAD_WAIT_SECONDS", "90"))


class _Slot:
    __slots__ = ("state_lock", "build_done", "building", "at", "data", "cold")

    def __init__(self) -> None:
        self.state_lock = threading.Lock()
        self.build_done = threading.Event()
        self.building = False
        self.at = 0.0
        self.data: Any = None
        self.cold = True


_slots: Dict[Hashable, _Slot] = {}
_registry_lock = threading.Lock()


def _slot(key: Hashable) -> _Slot:
    with _registry_lock:
        entry = _slots.get(key)
        if entry is None:
            entry = _Slot()
            _slots[key] = entry
        return entry


def clear_message_intel_load_cache() -> None:
    with _registry_lock:
        _slots.clear()


def db_cache_key(db: Any) -> str:
    return str(getattr(db, "db_path", id(db)))


def _fresh(slot: _Slot, ttl: float) -> bool:
    return (
        not slot.cold
        and slot.data is not None
        and (time.time() - float(slot.at)) < ttl
    )


def guarded_load(
    key: Hashable,
    loader: Callable[[], T],
    *,
    ttl: float | None = None,
    wait_timeout: float | None = None,
) -> Tuple[T, Dict[str, Any]]:
    """Run loader at most once per TTL; concurrent callers wait or get stale."""
    if ttl is None:
        ttl = DEFAULT_TTL
    if wait_timeout is None:
        wait_timeout = DEFAULT_WAIT
    slot = _slot(key)
    if _fresh(slot, ttl):
        return slot.data, {"cache": "hit"}

    with slot.state_lock:
        if _fresh(slot, ttl):
            return slot.data, {"cache": "hit"}
        if slot.building:
            need_wait = True
        else:
            slot.building = True
            slot.build_done.clear()
            need_wait = False

    if need_wait:
        slot.build_done.wait(timeout=wait_timeout)
        if _fresh(slot, ttl):
            return slot.data, {"cache": "hit"}
        if not slot.cold and slot.data is not None:
            return slot.data, {"cache": "stale_timeout", "stale": True}
        return slot.data, {"cache": "timeout"}

    try:
        data = loader()
        with slot.state_lock:
            slot.data = data
            slot.at = time.time()
            slot.cold = False
        return data, {"cache": "refresh"}
    finally:
        with slot.state_lock:
            slot.building = False
        slot.build_done.set()


def guarded_list_load(
    key: Hashable,
    loader: Callable[[], List[Any]],
    *,
    ttl: float | None = None,
    wait_timeout: float | None = None,
) -> List[Any]:
    data, _meta = guarded_load(key, loader, ttl=ttl, wait_timeout=wait_timeout)
    if data is None:
        return []
    return data if isinstance(data, list) else list(data)
