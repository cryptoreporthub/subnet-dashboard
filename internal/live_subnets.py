"""Live on-chain subnet feed (Bittensor/Substrate JSON-RPC via internal.chain_client).

Phase B1 of the subnet-dashboard hardening plan. Replaces the flaky TaoMarketCap
HTML scrape as the PRIMARY live data source for /api/subnets and the homepage,
killing the 33-day-stale registry.json fallback (audit finding #1).

Design note (deviation from IMPLEMENTATION_PLAN.md wording):
  The plan said "official bittensor SDK". This repo already ships a lightweight,
  dependency-free Bittensor-compatible JSON-RPC client in internal/chain_client.py
  (Layer 1 "primary" per its own docstring) that was never wired in. We USE that
  client instead of adding the heavy bittensor SDK (no torch bloat, reuses tested
  code). Same outcome, far less risk.

Syncing is heavy (many RPC calls), so it runs in a background daemon thread and is
cached to data/live_subnets.json with a sync timestamp. Reads are always cheap.
On any sync failure we keep the last good cache; get_all_subnets() falls back to the
existing TaoMarketCap + registry logic. The app never breaks.

SAFETY (added after a CI hang):
  - Background sync is FORCED OFF under CI / tests (GITHUB_ACTIONS, PYTEST_CURRENT_TEST, CI).
    In CI get_all_subnets() simply returns the committed registry (fast, no network).
  - The chain fetch is wrapped in a hard timeout (worker thread + join) so even if the
    upstream RPC has no socket timeout, the calling process can never block beyond
    LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS (default 60). The worker is daemon, so it never
    prevents interpreter shutdown.
"""
from __future__ import annotations

import json
import os
import threading
import time
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("live_subnets")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)
REGISTRY_PATH = os.path.join(REPO_ROOT, "config", "registry.json")
CACHE_PATH = os.path.join(REPO_ROOT, "data", "live_subnets.json")

SYNC_INTERVAL_SECONDS = int(os.environ.get("LIVE_SUBNETS_SYNC_INTERVAL_SECONDS", "300"))
MAX_STALE_SECONDS = int(os.environ.get("LIVE_SUBNETS_MAX_STALE_SECONDS", "1800"))
SYNC_TIMEOUT_SECONDS = float(os.environ.get("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", "60"))

# Default ON in production, but FORCE-OFF in CI/test environments so the heavy
# on-chain sync never touches the network (and thus never hangs a test run).
_auto_default = os.environ.get("LIVE_SUBNETS_AUTO_SYNC", "true").lower() in ("1", "true", "yes", "on")
_in_ci_or_test = bool(
    os.environ.get("GITHUB_ACTIONS") or os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CI")
)
AUTO_SYNC = _auto_default and not _in_ci_or_test
if _in_ci_or_test:
    logger.info("live_subnets: sync disabled in CI/test environment (AUTO_SYNC=False)")

_lock = threading.Lock()
_sync_loop_running = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_registry() -> Dict[str, Any]:
    try:
        with open(REGISTRY_PATH, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _registry_list() -> List[Dict[str, Any]]:
    reg = _read_registry()
    if isinstance(reg, dict):
        if "subnets" in reg and isinstance(reg["subnets"], list):
            return reg["subnets"]
        return list(reg.values())
    return []


def _netuid_of(rec: Dict[str, Any]) -> Optional[int]:
    for k in ("netuid", "id", "subnet_id"):
        v = rec.get(k)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return None


def _merge_into_registry(live: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_netuid = {}
    for r in live:
        n = _netuid_of(r)
        if n is not None:
            by_netuid[n] = r
    out = []
    seen = set()
    for rec in _registry_list():
        n = _netuid_of(rec)
        if n is None:
            out.append(rec)
            continue
        seen.add(n)
        merged = dict(rec)
        lv = by_netuid.get(n)
        if lv:
            for f in ("price", "stake", "total_stake", "emission", "liquidity",
                      "total_tao", "total_alpha", "root_prop",
                      "buys_24hr", "sells_24hr", "buy_volume_24h", "sell_volume_24h"):
                if f in lv and lv[f] not in (None, ""):
                    merged[f] = lv[f]
            merged["source"] = "blockmachine"
            merged["live"] = True
        else:
            merged["live"] = False
        out.append(merged)
    for n, lv in by_netuid.items():
        if n not in seen:
            out.append(lv)
    return out


def _fetch_chain_data():
    result = {}
    err = {}

    def _run():
        try:
            from internal.chain_client import get_default_client
            client = get_default_client()
            result["data"] = client.get_all_subnet_data()
        except Exception as exc:
            err["exc"] = exc

    worker = threading.Thread(target=_run, daemon=True, name="live-subnets-fetch")
    worker.start()
    worker.join(timeout=SYNC_TIMEOUT_SECONDS)
    if worker.is_alive():
        logger.warning("live_subnets sync timed out after %.0fs (worker still running in background)", SYNC_TIMEOUT_SECONDS)
        return None
    if "exc" in err:
        logger.warning("live_subnets sync failed: %s", err["exc"])
        return None
    return result.get("data")


def _sync_once() -> bool:
    raw = _fetch_chain_data()
    if not raw:
        return False
    merged = _merge_into_registry(raw)
    payload = {
        "synced_at": _now_iso(),
        "source": "blockmachine",
        "count": len(merged),
        "subnets": merged,
    }
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        tmp = CACHE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, CACHE_PATH)
        logger.info("live_subnets sync OK: %d subnets", len(merged))
        return True
    except Exception as exc:
        logger.warning("live_subnets cache write failed: %s", exc)
        return False


def get_live_subnets() -> List[Dict[str, Any]]:
    try:
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH, "r") as f:
                data = json.load(f)
            subnets = data.get("subnets", [])
            if subnets:
                _maybe_schedule_sync(data)
                return subnets
    except Exception:
        pass
    _maybe_schedule_sync(None)
    return _registry_list()


def _maybe_schedule_sync(cache_data):
    if not AUTO_SYNC:
        return
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"):
        return
    stale = True
    if cache_data and cache_data.get("synced_at"):
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(cache_data["synced_at"])).total_seconds()
            stale = age > MAX_STALE_SECONDS
        except Exception:
            stale = True
    if stale:
        _ensure_sync_loop()


def _ensure_sync_loop() -> None:
    global _sync_loop_running
    if not AUTO_SYNC:
        return
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"):
        return
    with _lock:
        if _sync_loop_running:
            return
        _sync_loop_running = True
    t = threading.Thread(target=_sync_loop, daemon=True, name="live-subnets-sync")
    t.start()


def _sync_loop() -> None:
    global _sync_loop_running
    try:
        _sync_once()
        while True:
            time.sleep(SYNC_INTERVAL_SECONDS)
            _sync_once()
    except Exception as exc:
        logger.warning("live_subnets sync loop exited: %s", exc)
    finally:
        _sync_loop_running = False


def live_data_freshness() -> Dict[str, Any]:
    info = {
        "source": "blockmachine",
        "sync_enabled": AUTO_SYNC,
        "ci_or_test": _in_ci_or_test,
        "last_sync": None,
        "age_seconds": None,
        "subnet_count": 0,
        "stale": True,
        "cache_path": CACHE_PATH,
    }
    try:
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH, "r") as f:
                data = json.load(f)
            info["last_sync"] = data.get("synced_at")
            info["subnet_count"] = data.get("count", 0)
            if data.get("synced_at"):
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(data["synced_at"])).total_seconds()
                info["age_seconds"] = int(age)
                info["stale"] = age > MAX_STALE_SECONDS
    except Exception as exc:
        logger.debug("freshness read failed: %s", exc)
    return info
