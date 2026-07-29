"""Detect whether this process can read committed JSON/SQLite on the Fly volume."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


def _data_dir() -> str:
    return os.environ.get("DATA_DIR", "data")


def data_dir_is_mounted_volume() -> bool:
    """True when DATA_DIR is a real mount (Fly volume), not ephemeral container FS."""
    root = os.path.realpath(_data_dir())
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 2:
                    continue
                mount_point = parts[1]
                if mount_point == root or root.startswith(mount_point.rstrip("/") + "/"):
                    fstype = parts[2] if len(parts) > 2 else ""
                    if fstype in {"overlay", "rootfs", "tmpfs", "proc", "sysfs", "devtmpfs"}:
                        continue
                    if mount_point in {"/", "/app"}:
                        continue
                    return True
    except OSError:
        pass
    # Explicit opt-in for tests / non-Linux
    return os.environ.get("DATA_DIR_IS_VOLUME", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def has_local_volume_data() -> bool:
    """True when soul_map, pump ladder, or a non-trivial message_intel DB is present."""
    root = _data_dir()
    if not os.path.isdir(root):
        return False
    markers = (
        "soul_map.json",
        "pump_ladder.json",
        ".worker_heartbeat",
        os.path.join("pump_desk", "latest.json"),
    )
    for rel in markers:
        if os.path.isfile(os.path.join(root, rel)):
            return True
    db = os.path.join(root, "message_intel.db")
    try:
        if os.path.isfile(db) and os.path.getsize(db) > 8192:
            return True
    except OSError:
        pass
    return False


def worker_data_freshness() -> Optional[Dict[str, Any]]:
    """split_v2 web — worker owns live_subnets.json + TMC SQLite on the Fly volume."""
    if not needs_worker_volume_proxy():
        return None
    try:
        from internal.worker_proxy import fetch_worker_json_sync

        remote = fetch_worker_json_sync("/api/data-freshness")
        if isinstance(remote, dict) and "effective_source" in remote:
            return remote
    except Exception:
        pass
    return None


def needs_worker_volume_proxy() -> bool:
    """split_v2 web — proxy volume APIs unless *this* machine owns the Fly volume.

    Orphan JSON under /app/data on web (no volume mount) must not disable proxy —
    that caused stale July-era resolver ticks while the worker held the real volume.
    """
    from internal.run_mode import is_worker_mode, split_worker_v2_enabled

    if not split_worker_v2_enabled() or is_worker_mode():
        return False
    if data_dir_is_mounted_volume() and has_local_volume_data():
        # Partial migration: volume still attached to web — read local.
        return False
    return True
