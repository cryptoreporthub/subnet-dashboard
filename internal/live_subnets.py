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


def _cache_path() -> str:
    data_dir = os.environ.get("DATA_DIR", "data")
    if not os.path.isabs(data_dir):
        data_dir = os.path.join(REPO_ROOT, data_dir)
    return os.path.join(data_dir, "live_subnets.json")

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
            # RedTeam / scoring expect a single ``volume`` field.
            if merged.get("volume") in (None, ""):
                buy = float(lv.get("buy_volume_24h") or 0)
                sell = float(lv.get("sell_volume_24h") or 0)
                if buy or sell:
                    merged["volume"] = round(buy + sell, 2)
                elif lv.get("liquidity") not in (None, ""):
                    try:
                        merged["volume"] = float(lv["liquidity"])
                    except (TypeError, ValueError):
                        pass
            merged["source"] = "blockmachine"
            merged["live"] = True
        else:
            merged["live"] = False
        if merged.get("netuid") is None and n is not None:
            merged["netuid"] = n
        try:
            from internal.subnet_names import enrich_subnet_row
            merged = enrich_subnet_row(merged)
        except Exception:
            pass
        out.append(merged)
    for n, lv in by_netuid.items():
        if n not in seen:
            out.append(lv)
    return out


def _registry_netuids() -> List[int]:
    """Committed registry netuids — avoids 200-netuid RPC probe fallback."""
    out = []
    for rec in _registry_list():
        n = _netuid_of(rec)
        if n is not None:
            out.append(n)
    return sorted(set(out))


def _fetch_chain_data():
    result = {}
    err = {}

    def _run():
        try:
            from internal.chain_client import get_default_client
            client = get_default_client()
            netuids = _registry_netuids()
            mode = os.environ.get("LIVE_SUBNETS_FETCH_MODE", "lite").strip().lower()
            if mode in ("lite", "price"):
                result["data"] = client.get_subnet_price_rows(netuids)
            else:
                result["data"] = client.get_all_subnet_data(netuids=netuids or None)
        except Exception as exc:
            err["exc"] = exc

    worker = threading.Thread(target=_run, daemon=True, name="live-subnets-fetch")
    worker.start()
    timeout = float(os.environ.get("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", str(SYNC_TIMEOUT_SECONDS)))
    worker.join(timeout=timeout)
    if worker.is_alive():
        logger.warning(
            "live_subnets sync timed out after %.0fs (worker still running in background)",
            timeout,
        )
        return None
    if "exc" in err:
        logger.warning("live_subnets sync failed: %s", err["exc"])
        return None
    return result.get("data")


def _boot_status_path() -> str:
    return os.path.join(os.path.dirname(_cache_path()), "live_subnets_boot.json")


def _record_boot_status(**fields: Any) -> None:
    try:
        payload = {"at": _now_iso(), **fields}
        path = _boot_status_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
    except Exception as exc:
        logger.debug("live_subnets boot status write failed: %s", exc)


def _read_boot_status() -> Dict[str, Any]:
    try:
        path = _boot_status_path()
        if os.path.isfile(path):
            with open(path, "r") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _sync_once() -> bool:
    _record_boot_status(phase="sync_start")
    raw = _fetch_chain_data()
    if raw is None:
        logger.warning("live_subnets sync: chain fetch failed or timed out")
        _record_boot_status(phase="sync_done", ok=False, reason="timeout")
        return False
    if not raw:
        logger.warning("live_subnets sync: chain fetch returned 0 subnets (RPC degraded?)")
        _record_boot_status(phase="sync_done", ok=False, reason="empty", rows=0)
        return False
    merged = _merge_into_registry(raw)
    payload = {
        "synced_at": _now_iso(),
        "source": "blockmachine",
        "count": len(merged),
        "subnets": merged,
    }
    try:
        os.makedirs(os.path.dirname(_cache_path()), exist_ok=True)
        tmp = _cache_path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, _cache_path())
        logger.info("live_subnets sync OK: %d subnets", len(merged))
        _record_boot_status(phase="sync_done", ok=True, rows=len(merged))
        return True
    except Exception as exc:
        logger.warning("live_subnets cache write failed: %s", exc)
        _record_boot_status(phase="sync_done", ok=False, reason=f"write:{exc}")
        return False


def bootstrap_live_subnets_cache() -> bool:
    """One-shot chain sync on dedicated worker boot (LIVE_SUBNETS_BOOT_IMMEDIATE=on)."""
    if not AUTO_SYNC:
        return False
    if _in_ci_or_test:
        return False
    from internal.run_mode import is_worker_mode

    # Dedicated worker always syncs on boot — do not gate on LIVE_SUBNETS_BOOT_IMMEDIATE.
    if not is_worker_mode():
        flag = os.environ.get("LIVE_SUBNETS_BOOT_IMMEDIATE", "off").strip().lower()
        if flag not in ("1", "true", "yes", "on"):
            return False
    logger.info("live_subnets bootstrap immediate sync")
    return _sync_once()


def get_live_subnets() -> List[Dict[str, Any]]:
    try:
        if os.path.exists(_cache_path()):
            with open(_cache_path(), "r") as f:
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
    try:
        from internal.data_volume import worker_data_freshness

        remote = worker_data_freshness()
        if remote:
            return remote
    except Exception:
        pass
    info = {
        "source": "blockmachine",
        "sync_enabled": AUTO_SYNC,
        "ci_or_test": _in_ci_or_test,
        "last_sync": None,
        "age_seconds": None,
        "subnet_count": 0,
        "stale": True,
        "cache_path": _cache_path(),
    }
    try:
        if os.path.exists(_cache_path()):
            with open(_cache_path(), "r") as f:
                data = json.load(f)
            info["last_sync"] = data.get("synced_at")
            info["subnet_count"] = data.get("count", 0)
            if data.get("synced_at"):
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(data["synced_at"])).total_seconds()
                info["age_seconds"] = int(age)
                info["stale"] = age > MAX_STALE_SECONDS
    except Exception as exc:
        logger.debug("freshness read failed: %s", exc)
    try:
        from internal.subnets.feed import probe_feed_layers

        probe = probe_feed_layers()
        info["effective_source"] = probe.get("effective_source")
        info["effective_total"] = probe.get("likely_total")
        info["registry_count"] = probe.get("registry_count")
        info["tmc_cache_count"] = (probe.get("tmc_cache") or {}).get("count", 0)
    except Exception as exc:
        logger.debug("effective feed probe failed: %s", exc)
    try:
        from internal.chain_client import get_default_client

        info["rpc_healthy"] = get_default_client().is_healthy()
    except Exception:
        info["rpc_healthy"] = None
    try:
        from internal.run_mode import get_run_mode, worker_heavy_feeds_enabled

        info["run_mode"] = get_run_mode()
        info["worker_heavy"] = worker_heavy_feeds_enabled()
    except Exception:
        pass
    boot = _read_boot_status()
    if boot:
        info["boot_status"] = boot
    if info.get("run_mode") == "worker":
        try:
            from internal.chain_client import get_default_client

            info["sample_price_sn1"] = get_default_client().get_alpha_price(1)
        except Exception as exc:
            info["sample_price_sn1"] = None
            info["sample_price_error"] = str(exc)[:120]
    return info
