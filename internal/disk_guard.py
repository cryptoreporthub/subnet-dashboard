"""Free-space checks on the committed DATA_DIR volume (#1399 slice 2c)."""

from __future__ import annotations

import os
import shutil
from typing import Any, Dict, NamedTuple, Optional

from internal.data_volume import data_dir_is_mounted_volume, resolved_data_dir

# Warn band above recorder floor (200→300 MB at defaults; scales with CHAIN_PRICE_MIN_FREE_MB).
_WARN_EXTRA_MB = int(os.environ.get("CHAIN_PRICE_WARN_EXTRA_MB", "100"))


class DiskUsage(NamedTuple):
    free: int
    used: int
    total: int


def readiness_thresholds_mb() -> tuple[int, int]:
    """Issue/warn free-space floors aligned with chain price recorder guard."""
    from internal.chain_price import config as chain_cfg

    low = int(chain_cfg.CHAIN_PRICE_MIN_FREE_MB)
    return low, low + _WARN_EXTRA_MB


def data_volume_usage() -> DiskUsage:
    """Bytes free/used/total for resolved DATA_DIR on this process."""
    usage = shutil.disk_usage(resolved_data_dir())
    return DiskUsage(free=usage.free, used=usage.used, total=usage.total)


def data_free_bytes() -> int:
    return data_volume_usage().free


def is_low(min_free_mb: int) -> bool:
    floor = int(min_free_mb) * 1024 * 1024
    return data_free_bytes() < floor


def _flags_for_free_bytes(free_bytes: int, low_mb: int, warn_mb: int) -> tuple[bool, bool]:
    free_mb = free_bytes / (1024 * 1024)
    return free_mb < low_mb, free_mb < warn_mb


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
        "owner": "local",
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
            "owner": "worker_proxy",
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
            "owner": "worker_proxy",
            "mounted": None,
            "path": resolved_data_dir(),
            "min_free_mb": low_mb,
            "warn_free_mb": warn_mb,
            "topology": "split_v2_web_proxy",
        }

    block = dict(remote)
    block["owner"] = "worker_proxy"
    block["topology"] = "split_v2_web_proxy"
    block.setdefault("min_free_mb", low_mb)
    block.setdefault("warn_free_mb", warn_mb)
    return block


def disk_usage_for_metrics() -> Optional[DiskUsage]:
    """Bytes for Prometheus; proxies worker volume in split_v2 when configured."""
    from internal.data_volume import needs_worker_volume_proxy

    if needs_worker_volume_proxy():
        block = build_data_volume_readiness()
        if block.get("status") == "unavailable" or not block.get("mounted"):
            return None
        free_b = block.get("free_bytes")
        used_b = block.get("used_bytes")
        total_b = block.get("total_bytes")
        if free_b is None or used_b is None or total_b is None:
            return None
        return DiskUsage(free=int(free_b), used=int(used_b), total=int(total_b))

    try:
        return data_volume_usage()
    except OSError:
        return None
