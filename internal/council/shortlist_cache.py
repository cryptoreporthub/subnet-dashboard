"""TTL cache for council deliberation shortlist (weighed / simivision hydrate)."""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional

TTL_SEC = int(os.environ.get("SHORTLIST_CACHE_SECONDS", "180"))

_store: Dict[str, Any] = {"key": None, "ts": 0.0, "shortlist": []}


def _cache_key(pick_payload: Optional[Dict[str, Any]]) -> str:
    from internal.council.publish_gate import publish_gate_percent

    if not isinstance(pick_payload, dict):
        return "none"
    date = str(pick_payload.get("date") or "")
    action = str(pick_payload.get("action") or "").upper()
    pick = pick_payload.get("pick") if isinstance(pick_payload.get("pick"), dict) else {}
    cand = pick_payload.get("candidate") if isinstance(pick_payload.get("candidate"), dict) else {}
    block = pick or cand
    sn = block.get("subnet") if isinstance(block.get("subnet"), dict) else {}
    netuid = sn.get("netuid")
    return f"{date}:{action}:{netuid}:gate{publish_gate_percent()}"


def cached_shortlist(
    pick_payload: Optional[Dict[str, Any]],
    builder: Callable[[], List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    key = _cache_key(pick_payload)
    now = time.time()
    if _store["key"] == key and now - float(_store["ts"]) < TTL_SEC:
        cached = _store.get("shortlist")
        return list(cached) if isinstance(cached, list) else []
    shortlist = builder()
    _store.update(key=key, ts=now, shortlist=list(shortlist))
    return shortlist


def clear_shortlist_cache() -> None:
    _store.update(key=None, ts=0.0, shortlist=[])
