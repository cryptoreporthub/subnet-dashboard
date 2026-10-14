"""Free-space checks on the committed DATA_DIR volume (#1399 slice 2c)."""

from __future__ import annotations

import shutil
from typing import NamedTuple

from internal.data_volume import data_dir_is_mounted_volume, resolved_data_dir

# ops/readiness thresholds (Claude §2.6 follow-up ask 2)
READINESS_ISSUE_LOW_MB = 200
READINESS_WARN_LOW_MB = 300


class DiskUsage(NamedTuple):
    free: int
    used: int
    total: int


def data_volume_usage() -> DiskUsage:
    """Bytes free/used/total for resolved DATA_DIR."""
    usage = shutil.disk_usage(resolved_data_dir())
    return DiskUsage(free=usage.free, used=usage.used, total=usage.total)


def data_free_bytes() -> int:
    return data_volume_usage().free


def is_low(min_free_mb: int) -> bool:
    floor = int(min_free_mb) * 1024 * 1024
    return data_free_bytes() < floor


def build_data_volume_readiness() -> dict:
    """Mounted-volume disk snapshot for /api/ops/readiness."""
    path = resolved_data_dir()
    mounted = data_dir_is_mounted_volume()
    if not mounted:
        return {"mounted": False, "path": path}

    usage = data_volume_usage()
    free_mb = usage.free / (1024 * 1024)
    return {
        "mounted": True,
        "path": path,
        "free_bytes": usage.free,
        "used_bytes": usage.used,
        "total_bytes": usage.total,
        "warn": free_mb < READINESS_WARN_LOW_MB,
        "low": free_mb < READINESS_ISSUE_LOW_MB,
    }
