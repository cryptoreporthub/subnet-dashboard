"""Free-space checks on the committed DATA_DIR volume (#1399 slice 2c)."""

from __future__ import annotations

import os
import shutil
import threading
import time
from typing import Any, Dict, NamedTuple, Optional

from internal.chain_price.config import CHAIN_PRICE_MIN_FREE_MB, chain_price_warn_extra_mb
from internal.data_volume import data_dir_is_mounted_volume, resolved_data_dir

WORKER_VOLUME_OWNER = "worker_local"
WEB_VOLUME_OWNER = "web_local"
PROXY_VOLUME_OWNER = "worker_proxy"

_METRICS_CACHE_LOCK = threading.Lock()
_METRICS_CACHE: Optional[DiskUsage] = None
_METRICS_CACHE_AT = 0.0
_METRICS_REFRESH_INFLIGHT = False
_METRICS_CACHE_TTL_SECONDS = float(os.environ.get("DATA_VOLUME_METRICS_CACHE_SECONDS", "30"))


class DiskUsage(NamedTuple):
    free: int
    used: int
    total: int


def readiness_thresholds_mb() -> tuple[int, int]:
    """Issue/warn free-space floors aligned with chain price recorder guard."""
    low = int(CHAIN_PRICE_MIN_FREE_MB)
    return low, low + chain_price_warn_extra_mb()


def data_volume_usage_for_path(directory: str) -> DiskUsage:
    usage = shutil.disk_usage(directory)
    return DiskUsage(free=usage.free, used=usage.used, total=usage.total)


def data_volume_usage() -> DiskUsage:
    """Bytes free/used/total for resolved DATA_DIR on this process."""
    return data_volume_usage_for_path(resolved_data_dir())


def data_free_bytes() -> int:
    return data_volume_usage().free


def is_low(min_free_mb: int, *, path: Optional[str] = None) -> bool:
    floor = int(min_free_mb) * 1024 * 1024
    if path:
        directory = os.path.dirname(os.path.abspath(path)) or "."
        try:
            free = data_volume_usage_for_path(directory).free
        except OSError:
            return True
        return free < floor
    return data_free_bytes() < floor


def _flags_for_free_bytes(free_bytes: int, low_mb: int, warn_mb: int) -> tuple[bool, bool]:
    free_mb = free_bytes / (1024 * 1024)
    return free_mb < low_mb, free_mb < warn_mb


def _local_volume_owner() -> str:
    from internal.run_mode import is_worker_mode

    return WORKER_VOLUME_OWNER if is_worker_mode() else WEB_VOLUME_OWNER


def build_data_volume_readiness_local() -> Dict[str, Any]:
    """Disk snapshot for the process that owns DATA_DIR (v1 inline web or worker)."""
    from internal.run_mode import is_worker_mode, split_worker_v2_enabled

    path = resolved_data_dir()
    low_mb, warn_mb = readiness_thresholds_mb()
    topology = "v1_inline"
    if split_worker_v2_enabled():
        topology = "split_v2_worker" if is_worker_mode() else "split_v2_web_local"

    base: Dict[str, Any] = {
        "path": path,
        "min_free_mb": low_mb,
        "warn_free_mb": warn_mb,
        "owner": _local_volume_owner(),
        "topology": topology,
        "topology_note": (
            "Prod canon is v1 inline (one web machine, volume on web). "
            "split_v2 web without a local mount should use worker_proxy owner."
        ),
    }
    mounted = data_dir_is_mounted_volume()
    if not mounted:
        return {**base, "mounted": False}

    usage = data_volume_usage()
    low, warn = _flags_for_free_bytes(usage.free, low_mb, warn_mb)
    return {
        **base,
        "mounted": True,
        "free_bytes": usage.free,
        "used_bytes": usage.used,
        "total_bytes": usage.total,
        "warn": warn,
        "low": low,
    }


def _fetch_worker_data_volume() -> Optional[Dict[str, Any]]:
    from internal.worker_proxy import fetch_worker_json_sync

    remote = fetch_worker_json_sync("/api/ops/data-volume")
    if not isinstance(remote, dict):
        return None
    if remote.get("status") == "unavailable":
        return None
    if remote.get("owner") != WORKER_VOLUME_OWNER:
        return None
    return remote


def build_data_volume_readiness() -> Dict[str, Any]:
    """Public readiness block — worker proxy in split_v2 when web lacks the volume."""
    from internal.data_volume import needs_worker_volume_proxy

    if not needs_worker_volume_proxy():
        return build_data_volume_readiness_local()

    low_mb, warn_mb = readiness_thresholds_mb()
    try:
        remote = _fetch_worker_data_volume()
    except Exception as exc:
        return {
            "status": "unavailable",
            "owner": PROXY_VOLUME_OWNER,
            "mounted": None,
            "path": resolved_data_dir(),
            "min_free_mb": low_mb,
            "warn_free_mb": warn_mb,
            "topology": "split_v2_web_proxy",
            "error": str(exc)[:200],
        }

    if not remote:
        return {
            "status": "unavailable",
            "owner": PROXY_VOLUME_OWNER,
            "mounted": None,
            "path": resolved_data_dir(),
            "min_free_mb": low_mb,
            "warn_free_mb": warn_mb,
            "topology": "split_v2_web_proxy",
        }

    block = dict(remote)
    block["owner"] = PROXY_VOLUME_OWNER
    block["topology"] = "split_v2_web_proxy"
    block.setdefault("min_free_mb", low_mb)
    block.setdefault("warn_free_mb", warn_mb)
    return block


def _probe_disk_usage_for_metrics() -> Optional[DiskUsage]:
    """Blocking probe (worker HTTP or local mount). Run off the event loop only."""
    from internal.data_volume import needs_worker_volume_proxy

    if needs_worker_volume_proxy():
        block = _fetch_worker_data_volume()
        if not block or not block.get("mounted"):
            return None
        free_b = block.get("free_bytes")
        used_b = block.get("used_bytes")
        total_b = block.get("total_bytes")
        if free_b is None or used_b is None or total_b is None:
            return None
        return DiskUsage(free=int(free_b), used=int(used_b), total=int(total_b))

    if not data_dir_is_mounted_volume():
        return None
    try:
        return data_volume_usage()
    except OSError:
        return None


def refresh_data_volume_metrics_cache_sync() -> None:
    """Refresh cached volume bytes (sync; for background thread or tests)."""
    global _METRICS_CACHE, _METRICS_CACHE_AT
    usage = _probe_disk_usage_for_metrics()
    with _METRICS_CACHE_LOCK:
        _METRICS_CACHE = usage
        _METRICS_CACHE_AT = time.monotonic()


def _schedule_metrics_cache_refresh() -> None:
    global _METRICS_REFRESH_INFLIGHT
    now = time.monotonic()
    with _METRICS_CACHE_LOCK:
        if (now - _METRICS_CACHE_AT) < _METRICS_CACHE_TTL_SECONDS:
            return
        if _METRICS_REFRESH_INFLIGHT:
            return
        _METRICS_REFRESH_INFLIGHT = True

    def _run() -> None:
        global _METRICS_REFRESH_INFLIGHT
        try:
            refresh_data_volume_metrics_cache_sync()
        finally:
            with _METRICS_CACHE_LOCK:
                _METRICS_REFRESH_INFLIGHT = False

    threading.Thread(target=_run, daemon=True, name="data-volume-metrics").start()


def disk_usage_for_metrics() -> Optional[DiskUsage]:
    """Last cached volume bytes for Prometheus (never blocks on worker HTTP)."""
    _schedule_metrics_cache_refresh()
    with _METRICS_CACHE_LOCK:
        return _METRICS_CACHE
