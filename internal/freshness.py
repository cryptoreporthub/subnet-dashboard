"""
Freshness layer for Subnet Pulse.

Tracks when each data source was last updated, detects staleness, and
runs a lightweight background refresh of registry metadata from the
public taostat source. Safe for Fly.io single-worker deployment; no
extra infrastructure required.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

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

_sync_state: Dict[str, Any] = {
    "last_sync_at": None,
    "last_sync_ok": None,
    "last_sync_error": None,
    "next_sync_at": None,
    "background_running": False,
    "last_refresh_at": 0.0,  # Timestamp for request-triggered checks
}

_timer: Optional[threading.Timer] = None
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


# ------------------------------------------------------------------
# Request-triggered refresh API (backward compatible)
# ------------------------------------------------------------------
def should_refresh_freshness(interval_seconds: int = BACKGROUND_INTERVAL_SECONDS) -> bool:
    """Check if enough time has passed since last registry refresh."""
    elapsed = time.time() - _sync_state["last_refresh_at"]
    return elapsed >= interval_seconds


def check_and_refresh_registry(immediate: bool = False) -> Dict[str, Any]:
    """
    Check if refresh is due and run if so.
    This is the main entry point for request-triggered execution.
    """
    if not immediate and not should_refresh_freshness():
        return {
            "ok": True,
            "skipped": True,
            "reason": "not due yet",
            "last_sync_at": _sync_state["last_sync_at"],
        }
    
    result = merge_remote_registry()
    with _lock:
        _sync_state["last_refresh_at"] = time.time()
    return result


def start_background_sync(immediate: bool = False) -> Dict[str, Any]:
    """Start background sync. For Fly.io compatibility, prefer request-triggered."""
    global _timer
    with _lock:
        _sync_state["background_running"] = True
        _sync_state["last_refresh_at"] = time.time()
    
    if immediate:
        # Run immediately in background thread
        threading.Thread(target=merge_remote_registry, daemon=True).start()
        return {"started": True, "mode": "immediate"}
    else:
        # Schedule first tick in 1 minute, then every BACKGROUND_INTERVAL_SECONDS
        def _schedule_and_run():
            time.sleep(60)  # Wait 1 minute before first run
            while _sync_state["background_running"]:
                merge_remote_registry()
                with _lock:
                    _sync_state["last_refresh_at"] = time.time()
                time.sleep(BACKGROUND_INTERVAL_SECONDS)
        
        t = threading.Thread(target=_schedule_and_run, daemon=True)
        t.start()
        return {"started": True, "mode": "background_timer"}


def stop_background_sync() -> Dict[str, Any]:
    """Stop background sync."""
    global _timer
    with _lock:
        _sync_state["background_running"] = False
        if _timer:
            _timer.cancel()
            _timer = None
    return {"stopped": True}


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
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        temp_path = registry_path + ".tmp"
        with open(temp_path, "w") as f:
            json.dump(local, f, indent=2)
        os.replace(temp_path, registry_path)
    except Exception as e:
        result["error"] = f"failed to write registry: {e}"
        return result

    # Update sync state
    with _lock:
        _sync_state["last_sync_at"] = result["updated_at"]
        _sync_state["last_sync_ok"] = True
        _sync_state["last_sync_error"] = None

    result["ok"] = True
    result["updated_count"] = updated_count
    return result