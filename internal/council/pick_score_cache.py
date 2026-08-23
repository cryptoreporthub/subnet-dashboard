"""Epoch-keyed per-subnet score cache for daily-pick scoring.

Cache key: (netuid, tmc_data_epoch_unix, context_hash).  Epoch source is
``internal.indicators.tmc_epoch.tmc_data_epoch_unix`` — the min of both
TMC ``cached_at`` timestamps that single-flight refreshes together.

When ``tmc_epoch.is_epoch_stale()`` is true the cache is bypassed entirely
(``cache=bypass_stale``) so a stale epoch cannot masquerade as a hit.

**Prod footprint (2026-08-23, deploy 0acd6922):** median ~5,827 B/entry for a
full ``score_subnet_for_day`` payload (not the minimal unit-test fake).
Steady state 20 subnets × 3 epochs ≈ 60 entries ≈ 350 KB (~68% of the 512 KiB
byte cap).  The byte cap binds before the 256-entry cap.

**Eviction:** FIFO by insertion timestamp (``stored_at``); hits do not refresh
recency.  Not LRU.

**Hit window (observed prod):** TMC ``cached_at`` can advance during a pick's
own scoring run, so the effective shared-epoch window is ~30–40s — shorter than
the 60s TTL.  Sequential picks ~21s apart still missed (epoch rotated).  Cache
earns only on sub-rotation re-picks; scheduler cadence (15min/24h) yields ≈zero
prod hit-rate by design, not defect.  Epoch pinning shelved (no current consumer).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from internal.indicators.tmc_epoch import is_epoch_stale, tmc_data_epoch_unix

logger = logging.getLogger(__name__)

CACHE_PATH = os.environ.get("DPICK_SCORE_CACHE_PATH", os.path.join("data", "pick_score_cache.json"))
LOCK_PATH = CACHE_PATH + ".lock"
MAX_ENTRIES = int(os.environ.get("DPICK_SCORE_CACHE_MAX_ENTRIES", "256"))
# ponytail: measured ~5.8KB/entry on prod (full score_subnet_for_day dict); byte cap
# binds before entry cap (256 × ~5.8KB ≈ 1.46MB > 512KiB).  Steady 60 entries ≈ 350KB.
MAX_BYTES = int(os.environ.get("DPICK_SCORE_CACHE_MAX_BYTES", "524288"))  # 512 KiB hard cap

_session_lock = threading.Lock()


def _context_hash(market_context: Optional[Dict[str, Any]]) -> str:
    ctx = market_context or {}
    weights = ctx.get("weights") if isinstance(ctx.get("weights"), dict) else {}
    payload = {
        "tao": round(float(ctx.get("tao_change_24h", 0) or 0), 4),
        "weights": sorted((k, round(float(v or 0), 4)) for k, v in weights.items()),
        "breadth": ctx.get("breadth"),
        "volatility": round(float(ctx.get("volatility", 0) or 0), 4),
    }
    return hashlib.md5(
        json.dumps(payload, sort_keys=True).encode(),
        usedforsecurity=False,
    ).hexdigest()[:12]


def _entry_key(netuid: int, epoch_unix: float, ctx_hash: str) -> str:
    return f"{int(netuid)}:{epoch_unix:.3f}:{ctx_hash}"


def _entry_bytes(entry: Dict[str, Any]) -> int:
    return len(json.dumps(entry, sort_keys=True).encode("utf-8"))


def _empty_store() -> Dict[str, Any]:
    return {"version": 1, "entries": {}, "total_bytes": 0}


def _load_store_unlocked() -> Dict[str, Any]:
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
            return _empty_store()
        data.setdefault("version", 1)
        data.setdefault("total_bytes", sum(_entry_bytes(e) for e in data["entries"].values()))
        return data
    except FileNotFoundError:
        return _empty_store()
    except Exception as exc:
        logger.warning("pick_score_cache: load failed (%s); starting empty", exc)
        return _empty_store()


def _save_store_unlocked(store: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, sort_keys=True, separators=(",", ":"))
    os.replace(tmp, CACHE_PATH)


def _with_file_lock(fn):
    os.makedirs(os.path.dirname(LOCK_PATH) or ".", exist_ok=True)
    with open(LOCK_PATH, "a", encoding="utf-8") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def _evict(store: Dict[str, Any]) -> None:
    """Drop oldest entries by stored_at until within byte/entry caps (FIFO, not LRU)."""
    entries: Dict[str, Any] = store["entries"]
    while len(entries) > MAX_ENTRIES or int(store.get("total_bytes", 0)) > MAX_BYTES:
        if not entries:
            store["total_bytes"] = 0
            return
        oldest_key = min(entries, key=lambda k: float(entries[k].get("stored_at", 0.0)))
        store["total_bytes"] = max(0, int(store.get("total_bytes", 0)) - _entry_bytes(entries[oldest_key]))
        del entries[oldest_key]


def begin_session(market_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Open a pick-scoring cache session.  Call once per select_daily_pick."""
    bypass = is_epoch_stale()
    epoch_unix = tmc_data_epoch_unix()
    ctx_hash = _context_hash(market_context)
    store = _with_file_lock(_load_store_unlocked)
    return {
        "bypass": bypass,
        "epoch_unix": epoch_unix,
        "ctx_hash": ctx_hash,
        "store": store,
        "pending": {},  # new entries this pick (netuid -> entry)
        "write_lock": threading.Lock(),
    }


def lookup(session: Dict[str, Any], netuid: int) -> Tuple[Optional[Dict[str, Any]], str]:
    """Return (cached_score_or_None, cache_status)."""
    if session.get("bypass"):
        return None, "bypass_stale"
    key = _entry_key(netuid, float(session["epoch_unix"]), session["ctx_hash"])
    entry = session["store"]["entries"].get(key)
    if entry and isinstance(entry.get("score"), dict):
        return entry["score"], "hit"
    return None, "miss"


def store(session: Dict[str, Any], netuid: int, score: Dict[str, Any]) -> str:
    """Cache a freshly computed score.  Returns cache status ('miss' or 'bypass_stale')."""
    if session.get("bypass"):
        return "bypass_stale"
    key = _entry_key(netuid, float(session["epoch_unix"]), session["ctx_hash"])
    entry = {
        "netuid": int(netuid),
        "epoch_unix": float(session["epoch_unix"]),
        "ctx_hash": session["ctx_hash"],
        "score": score,
        "stored_at": time.time(),
    }
    with session["write_lock"]:
        session["pending"][int(netuid)] = (key, entry)
    return "miss"


def end_session(session: Dict[str, Any]) -> None:
    """Persist pending entries from this pick (best-effort)."""
    pending: Dict[int, Tuple[str, Dict[str, Any]]] = session.get("pending") or {}
    if not pending:
        return

    def _merge() -> None:
        store = _load_store_unlocked()
        entries: Dict[str, Any] = store["entries"]
        total_bytes = int(store.get("total_bytes", 0))
        for _netuid, (key, entry) in pending.items():
            if key in entries:
                total_bytes -= _entry_bytes(entries[key])
            entries[key] = entry
            total_bytes += _entry_bytes(entry)
        store["total_bytes"] = total_bytes
        _evict(store)
        _save_store_unlocked(store)

    try:
        _with_file_lock(_merge)
    except Exception as exc:
        logger.warning("pick_score_cache: persist failed (%s)", exc)


def clear_for_tests() -> None:
    """Drop on-disk cache (tests only)."""
    with _session_lock:
        try:
            os.remove(CACHE_PATH)
        except FileNotFoundError:
            pass
        try:
            os.remove(LOCK_PATH)
        except FileNotFoundError:
            pass


def list_epoch_keys(store: Optional[Dict[str, Any]] = None) -> List[float]:
    """Distinct epoch_unix values in *store* (or on disk).  Test helper."""
    if store is None:
        store = _with_file_lock(_load_store_unlocked)
    epochs = {float(e.get("epoch_unix", 0.0)) for e in store.get("entries", {}).values()}
    return sorted(epochs)
