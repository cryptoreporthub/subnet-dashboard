"""Single-flight + short TTL cache for heavy message_intel SQLite loads."""

from __future__ import annotations

import copy
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Hashable, List, Optional, Tuple, TypeVar

T = TypeVar("T")

DEFAULT_TTL = float(os.environ.get("MESSAGE_INTEL_LOAD_CACHE_SECONDS", "30"))
DEFAULT_WAIT = float(os.environ.get("MESSAGE_INTEL_LOAD_WAIT_SECONDS", "15"))
MAX_CACHE_SLOTS = int(os.environ.get("MESSAGE_INTEL_LOAD_MAX_SLOTS", "128"))
MAX_CACHE_OFFSET = int(os.environ.get("MESSAGE_INTEL_MAX_CACHE_OFFSET", "200"))


class LoadTimeout(TimeoutError):
    """Cold cache: an in-flight load did not finish before the wait budget."""


class _Slot:
    __slots__ = ("state_lock", "build_done", "building", "at", "data", "cold")

    def __init__(self) -> None:
        self.state_lock = threading.Lock()
        self.build_done = threading.Event()
        self.building = False
        self.at = 0.0
        self.data: Any = None
        self.cold = True


_slots: "OrderedDict[Hashable, _Slot]" = OrderedDict()
_registry_lock = threading.Lock()


def _evict_stale_slots() -> None:
    for key in list(_slots.keys()):
        slot = _slots[key]
        if slot.building:
            continue
        if slot.cold:
            del _slots[key]


def _slot(key: Hashable) -> _Slot:
    with _registry_lock:
        _evict_stale_slots()
        entry = _slots.get(key)
        if entry is not None:
            _slots.move_to_end(key)
            return entry
        while len(_slots) >= MAX_CACHE_SLOTS:
            _slots.popitem(last=False)
        entry = _Slot()
        _slots[key] = entry
        return entry


def clear_message_intel_load_cache() -> None:
    with _registry_lock:
        _slots.clear()


def invalidate_key(key: Hashable) -> None:
    with _registry_lock:
        _slots.pop(key, None)


def db_cache_key(db: Any) -> str:
    return str(getattr(db, "db_path", id(db)))


def list_messages_guard_key(
    db_path: str,
    limit: int,
    offset: int,
    *,
    kind: str,
) -> Optional[Hashable]:
    """Do not cache unbounded pagination keys (large offset)."""
    if int(offset) > MAX_CACHE_OFFSET:
        return None
    return (kind, db_path, int(limit), int(offset))


def engine_list_messages_guard_key(
    db_path: str,
    limit: int,
    offset: int,
    min_conviction: Any,
    netuid: Any,
    topic: Any,
    author_id: Any,
) -> Optional[Hashable]:
    if int(offset) > MAX_CACHE_OFFSET:
        return None
    return (
        "engine.list_messages",
        db_path,
        int(limit),
        int(offset),
        min_conviction,
        netuid,
        topic,
        author_id,
    )


def _fresh(slot: _Slot, ttl: float) -> bool:
    return (
        not slot.cold
        and slot.data is not None
        and (time.time() - float(slot.at)) < ttl
    )


def _isolate(value: Any) -> Any:
    if isinstance(value, list):
        return [copy.copy(row) if isinstance(row, dict) else row for row in value]
    if isinstance(value, dict):
        return copy.deepcopy(value)
    return value


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
        return _isolate(slot.data), {"cache": "hit"}

    with slot.state_lock:
        if _fresh(slot, ttl):
            return _isolate(slot.data), {"cache": "hit"}
        if slot.building:
            if not slot.cold and slot.data is not None:
                return _isolate(slot.data), {"cache": "stale_immediate", "stale": True}
            need_wait = True
        else:
            slot.building = True
            slot.build_done.clear()
            need_wait = False

    if need_wait:
        slot.build_done.wait(timeout=wait_timeout)
        if _fresh(slot, ttl):
            return _isolate(slot.data), {"cache": "hit"}
        if not slot.cold and slot.data is not None:
            return _isolate(slot.data), {"cache": "stale_timeout", "stale": True}
        raise LoadTimeout(f"message_intel load still in flight for key={key!r}")

    try:
        data = loader()
        with slot.state_lock:
            slot.data = data
            slot.at = time.time()
            slot.cold = False
        return _isolate(data), {"cache": "refresh"}
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
