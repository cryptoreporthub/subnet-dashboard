"""
Freshness layer for Subnet Pulse.

Tracks when each data source was last updated, detects staleness, and
runs a lightweight background refresh of registry metadata from the
public taostat source. Safe for Fly.io single-worker deployment; no
extra infrastructure required.
"""

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from internal.job_scheduler import cancel_job, schedule_interval_seconds

REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
WATCHLIST_PATH = os.environ.get("WATCHLIST_PATH", "config/watchlist.json")
SIGNAL_TIMELINE_PATH = os.environ.get("SIGNAL_TIMELINE_PATH", "data/signal_timeline.json")
PRICE_CACHE_PATH = os.environ.get("PRICE_CACHE_PATH", "data/price_cache.json")
REMOTE_REGISTRY_URL = os.environ.get(
    "REMOTE_REGISTRY_URL",
    "https://raw.githubusercontent.com/taostat/subnets-infos/main/subnets.json",
)

# Staleness thresholds in seconds.
THRESHOLDS: Dict[str, int] = {
    "registry": int(os.environ.get("REGISTRY_STALE_SECONDS", "300")),
    "soul_map": int(os.environ.get("SOUL_MAP_STALE_SECONDS", "3600")),
    "recommendations": int(os.environ.get("RECOMMENDATIONS_STALE_SECONDS", "600")),
    "watchlist": int(os.environ.get("WATCHLIST_STALE_SECONDS", "300")),
    "signal_timeline": int(os.environ.get("SIGNAL_TIMELINE_STALE_SECONDS", "300")),
    "price_cache": int(os.environ.get("PRICE_CACHE_STALE_SECONDS", "900")),
}

BACKGROUND_INTERVAL_SECONDS = int(
    os.environ.get("BACKGROUND_SYNC_INTERVAL_SECONDS", "300")
)
JOB_ID = "freshness-background-sync"

_sync_state: Dict[str, Any] = {
    "last_sync_at": None,
    "last_sync_ok": None,
    "last_sync_error": None,
    "next_sync_at": None,
    "background_running": False,
}

_timer: Optional[object] = None  # legacy name kept for tests that import the symbol
_lock = threading.Lock()

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # Python 3.10+ handles timezone-aware ISO strings.
        return datetime.fromisoformat(value)
    except Exception:
        return None

def _file_mtime(path: str) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    except Exception:
        return None

def source_freshness(
    path: str,
    threshold_seconds: int,
    embedded_updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Return freshness metadata for a file-backed data source."""
    last_updated = None
    source = "unknown"

    if embedded_updated_at:
        parsed = _parse_iso(embedded_updated_at)
        if parsed:
            last_updated = embedded_updated_at
            source = "embedded"

    if last_updated is None and os.path.exists(path):
        mtime = _file_mtime(path)
        if mtime:
            last_updated = mtime.isoformat()
            source = "file_mtime"

    age_seconds = None
    is_stale = False
    if last_updated:
        parsed = _parse_iso(last_updated)
        if parsed:
            age_seconds = int((datetime.now(timezone.utc) - parsed).total_seconds())
            is_stale = age_seconds > threshold_seconds
    elif not os.path.exists(path):
        # A missing data source is treated as stale so dashboards can
        # surface the degradation rather than silently showing nothing.
        is_stale = True

    return {
        "last_updated": last_updated,
        "age_seconds": age_seconds,
        "threshold_seconds": threshold_seconds,
        "is_stale": is_stale,
        "source": source,
    }

def registry_freshness(registry_path: str = REGISTRY_PATH) -> Dict[str, Any]:
    """Freshness for the registry file, using newest item timestamp if available."""
    newest: Optional[str] = None
    if os.path.exists(registry_path):
        try:
            with open(registry_path, "r") as f:
                data = json.load(f)
            for item in data.values():
                updated = item.get("last_updated")
                if updated and (newest is None or updated > newest):
                    newest = updated
        except Exception:
            pass
    return source_freshness(registry_path, THRESHOLDS["registry"], newest)

def soul_map_freshness(soul_map_path: str = SOUL_MAP_PATH) -> Dict[str, Any]:
    """Freshness for the soul-map state, using its embedded updated_at."""
    updated_at: Optional[str] = None
    if os.path.exists(soul_map_path):
        try:
            with open(soul_map_path, "r") as f:
                data = json.load(f)
            updated_at = data.get("soul_map_state", {}).get("updated_at")
        except Exception:
            pass
    return source_freshness(soul_map_path, THRESHOLDS["soul_map"], updated_at)

def recommendations_freshness(registry_path: str = REGISTRY_PATH) -> Dict[str, Any]:
    """Recommendations are derived from registry; mirror registry freshness."""
    return source_freshness(
        registry_path,
        THRESHOLDS["recommendations"],
        registry_freshness(registry_path).get("last_updated"),
    )

def watchlist_freshness(watchlist_path: str = WATCHLIST_PATH) -> Dict[str, Any]:
    """Freshness for the protocol watchlist file."""
    newest: Optional[str] = None
    if os.path.exists(watchlist_path):
        try:
            with open(watchlist_path, "r") as f:
                data = json.load(f)
            newest = data.get("last_updated")
        except Exception:
            pass
    return source_freshness(watchlist_path, THRESHOLDS["watchlist"], newest)

def signal_timeline_freshness(signal_timeline_path: str = SIGNAL_TIMELINE_PATH) -> Dict[str, Any]:
    """Freshness for the signal/pump-cycle timeline file."""
    newest: Optional[str] = None
    if os.path.exists(signal_timeline_path):
        try:
            with open(signal_timeline_path, "r") as f:
                data = json.load(f)
            newest = data.get("updated_at")
        except Exception:
            pass
    return source_freshness(signal_timeline_path, THRESHOLDS["signal_timeline"], newest)

def price_data_freshness(price_cache_path: str = PRICE_CACHE_PATH) -> Dict[str, Any]:
    """Freshness for the technical indicator price cache."""
    newest: Optional[str] = None
    if os.path.exists(price_cache_path):
        try:
            with open(price_cache_path, "r") as f:
                data = json.load(f)
            # Use the most recent fetched_at timestamp across cached subnets.
            for item in data.values():
                fetched = item.get("fetched_at")
                if fetched and (newest is None or fetched > newest):
                    newest = fetched
        except Exception:
            pass
    return source_freshness(price_cache_path, THRESHOLDS["price_cache"], newest)

def overall_freshness(
    registry_path: str = REGISTRY_PATH,
    soul_map_path: str = SOUL_MAP_PATH,
    watchlist_path: str = WATCHLIST_PATH,
    signal_timeline_path: str = SIGNAL_TIMELINE_PATH,
    price_cache_path: str = PRICE_CACHE_PATH,
) -> Dict[str, Any]:
    """Freshness snapshot for all tracked sources."""
    registry = registry_freshness(registry_path)
    soul_map = soul_map_freshness(soul_map_path)
    recommendations = recommendations_freshness(registry_path)
    watchlist = watchlist_freshness(watchlist_path)
    signal_timeline = signal_timeline_freshness(signal_timeline_path)
    price_cache = price_data_freshness(price_cache_path)
    any_stale = (
        registry["is_stale"]
        or soul_map["is_stale"]
        or recommendations["is_stale"]
        or watchlist["is_stale"]
        or signal_timeline["is_stale"]
        or price_cache["is_stale"]
    )
    return {
        "overall": {
            "any_stale": any_stale,
            "checked_at": _now_iso(),
        },
        "registry": registry,
        "soul_map": soul_map,
        "recommendations": recommendations,
        "watchlist": watchlist,
        "signal_timeline": signal_timeline,
        "price_cache": price_cache,
    }

def merge_remote_registry(
    registry_path: str = REGISTRY_PATH,
    remote_url: str = REMOTE_REGISTRY_URL,
) -> Dict[str, Any]:
    """
    Fetch the upstream subnet registry metadata and merge it into the
    local registry file. Existing economic fields are preserved; only
    descriptive metadata is refreshed.
    """
    result = {
        "ok": False,
        "updated_count": 0,
        "remote_url": remote_url,
        "error": None,
        "updated_at": _now_iso(),
    }

    local: Dict[str, Any] = {}
    if os.path.exists(registry_path):
        try:
            with open(registry_path, "r") as f:
                local = json.load(f)
        except Exception as e:
            result["error"] = f"failed to read local registry: {e}"
            return result

    try:
        if remote_url.startswith("file://"):
            path = remote_url[len("file://"):]
            with open(path, "r") as f:
                remote = json.load(f)
        else:
            response = requests.get(remote_url, timeout=30)
            response.raise_for_status()
            remote = response.json()
    except Exception as e:
        result["error"] = f"remote fetch failed: {e}"
        return result

    now = _now_iso()
    preserved_local = local.copy()
    updated_count = 0

    for key, remote_item in remote.items():
        local_item = local.get(key)
        if local_item is None:
            # Seed a new subnet with remote metadata and placeholders.
            local[key] = {
                "id": int(key),
                "name": remote_item.get("name"),
                "status": "unknown",
                "risk_flags": [],
                "last_updated": now,
                "sources": [remote_url],
                "emission_rank": None,
                "staking_data": {"total_stake": 0.0, "apy": 0.0},
                "emission": 0.0,
                "social_mentions": 0,
                "is_overvalued": False,
                "owner": remote_item.get("owner"),
                "github": remote_item.get("github"),
                "hw_requirements": remote_item.get("hw_requirements"),
                "image_url": remote_item.get("image_url"),
                "description": remote_item.get("description"),
            }
            updated_count += 1
            continue

        # Merge descriptive fields only.
        merge_fields = [
            "name",
            "owner",
            "github",
            "hw_requirements",
            "image_url",
            "description",
        ]
        changed = False
        for field in merge_fields:
            remote_value = remote_item.get(field)
            if remote_value and local_item.get(field) != remote_value:
                local_item[field] = remote_value
                changed = True

        # Always bump timestamp on a successful refresh so the dashboard
        # knows the data is being actively maintained.
        local_item["last_updated"] = now
        if changed:
            updated_count += 1

    # If remote shrunk (subnets removed), leave local entries intact so the
    # dashboard doesn't silently disappear data. They will simply age out.

    if updated_count == 0 and local == preserved_local:
        # Still bump timestamps to show the sync ran and data is fresh.
        for item in local.values():
            item["last_updated"] = now

    try:
        dir_name = os.path.dirname(registry_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=dir_name or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(local, f, indent=2)
            os.replace(temp_path, registry_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    except Exception as e:
        result["error"] = f"failed to write registry: {e}"
        return result

    result["ok"] = True
    result["updated_count"] = updated_count
    return result


def merge_ladder_names_into_registry(
    registry_path: str = REGISTRY_PATH,
) -> Dict[str, Any]:
    """Refresh registry display names from the live pump ladder (desk-trusted labels)."""
    result: Dict[str, Any] = {
        "ok": False,
        "updated_count": 0,
        "error": None,
        "updated_at": _now_iso(),
    }
    try:
        from internal.pump.state import load_state
        from internal.subnet_names import _is_bad_name, _load_name_overrides

        ladder = load_state()
        subnets = ladder.get("subnets") if isinstance(ladder, dict) else {}
        if not isinstance(subnets, dict):
            subnets = {}
        overrides = _load_name_overrides()
    except Exception as exc:
        result["error"] = str(exc)
        return result

    local: Dict[str, Any] = {}
    if os.path.exists(registry_path):
        try:
            with open(registry_path, "r", encoding="utf-8") as handle:
                local = json.load(handle)
        except Exception as exc:
            result["error"] = f"failed to read local registry: {exc}"
            return result
    if not isinstance(local, dict):
        local = {}

    now = _now_iso()
    updated = 0
    import re

    for key, entry in subnets.items():
        if not isinstance(entry, dict):
            continue
        netuid = entry.get("netuid", key)
        try:
            sk = str(int(netuid))
        except (TypeError, ValueError):
            continue
        if sk in overrides:
            continue
        name = entry.get("name")
        if _is_bad_name(name):
            continue
        label = str(name).strip()
        if re.match(r"^SN\d+$", label, re.I):
            continue
        item = local.get(sk)
        if not isinstance(item, dict):
            continue
        if item.get("name") == label:
            continue
        item["name"] = label
        item["last_updated"] = now
        updated += 1

    if updated == 0:
        result["ok"] = True
        return result

    try:
        dir_name = os.path.dirname(registry_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=dir_name or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(local, handle, indent=2)
            os.replace(temp_path, registry_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    except Exception as exc:
        result["error"] = f"failed to write registry: {exc}"
        return result

    result["ok"] = True
    result["updated_count"] = updated
    return result


def refresh_watchlist(
    watchlist_path: str = WATCHLIST_PATH,
) -> Dict[str, Any]:
    """
    Refresh the protocol watchlist by bumping timestamps and ensuring the
    file is valid JSON. This keeps first-class protocols (VVV, FET, RENDER,
    TAO, HYPE) on the same 5-minute cadence as the subnet registry without
    interfering with the 128-subnet sweep.
    """
    result = {
        "ok": False,
        "watchlist_path": watchlist_path,
        "error": None,
        "updated_at": _now_iso(),
    }

    data: Dict[str, Any] = {}
    if os.path.exists(watchlist_path):
        try:
            with open(watchlist_path, "r") as f:
                data = json.load(f)
        except Exception as e:
            result["error"] = f"failed to read watchlist: {e}"
            return result

    now = _now_iso()
    data["last_updated"] = now
    protocols = data.get("protocols", {})
    for protocol in protocols.values():
        protocol["last_updated"] = now

    try:
        dir_name = os.path.dirname(watchlist_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=dir_name or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(temp_path, watchlist_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    except Exception as e:
        result["error"] = f"failed to write watchlist: {e}"
        return result

    result["ok"] = True
    result["protocol_count"] = len(protocols)
    return result


def refresh_all(
    registry_path: str = REGISTRY_PATH,
    soul_map_path: str = SOUL_MAP_PATH,
    watchlist_path: str = WATCHLIST_PATH,
    price_cache_path: str = PRICE_CACHE_PATH,
) -> Dict[str, Any]:
    """Run all available refresh steps and return a combined report."""
    result = {
        "synced_at": _now_iso(),
        "registry": merge_remote_registry(registry_path),
        "ladder_names": merge_ladder_names_into_registry(registry_path),
        "watchlist": refresh_watchlist(watchlist_path),
        "freshness": overall_freshness(registry_path, soul_map_path, watchlist_path, price_cache_path=price_cache_path),
    }
    return result


def _background_tick() -> None:
    report = refresh_all()
    with _lock:
        _sync_state["last_sync_at"] = report["synced_at"]
        _sync_state["last_sync_ok"] = report["registry"]["ok"]
        _sync_state["last_sync_error"] = report["registry"].get("error")
        _sync_state["next_sync_at"] = (
            datetime.now(timezone.utc).timestamp() + BACKGROUND_INTERVAL_SECONDS
        )


def start_background_sync(
    interval: int = BACKGROUND_INTERVAL_SECONDS,
    immediate: bool = False,
) -> Dict[str, Any]:
    """Start the background sync timer. Idempotent."""
    with _lock:
        if _sync_state["background_running"]:
            return {"started": False, "reason": "already running"}
        _sync_state["background_running"] = True
        _sync_state["next_sync_at"] = (
            datetime.now(timezone.utc).timestamp() + interval
        )

    if immediate:
        _background_tick()

    schedule_interval_seconds(
        JOB_ID, _background_tick, interval, start_delay_seconds=interval
    )
    return {"started": True, "interval_seconds": interval}


def stop_background_sync() -> Dict[str, Any]:
    """Stop the background sync timer."""
    with _lock:
        _sync_state["background_running"] = False
        _sync_state["next_sync_at"] = None
    cancel_job(JOB_ID)
    return {"stopped": True}


def get_sync_state(
    registry_path: str = REGISTRY_PATH,
    soul_map_path: str = SOUL_MAP_PATH,
    watchlist_path: str = WATCHLIST_PATH,
    signal_timeline_path: str = SIGNAL_TIMELINE_PATH,
    price_cache_path: str = PRICE_CACHE_PATH,
) -> Dict[str, Any]:
    """Combined freshness + background sync state for the API."""
    with _lock:
        state = dict(_sync_state)
    freshness = overall_freshness(registry_path, soul_map_path, watchlist_path, signal_timeline_path, price_cache_path)
    state["freshness"] = freshness
    return state