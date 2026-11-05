"""Detect whether this process can read committed JSON/SQLite on the Fly volume."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


def _data_dir() -> str:
    return os.environ.get("DATA_DIR", "data")


def resolved_data_dir() -> str:
    """Realpath of DATA_DIR (Fly: /app/data volume mount)."""
    return os.path.realpath(_data_dir())


_DISALLOWED_MOUNT_FSTYPES = frozenset(
    {"overlay", "rootfs", "tmpfs", "proc", "sysfs", "devtmpfs"}
)


def _read_mountinfo() -> list[str]:
    """Return /proc/self/mountinfo lines (empty when unavailable)."""
    try:
        with open("/proc/self/mountinfo", "r", encoding="utf-8") as handle:
            return handle.read().splitlines()
    except OSError:
        return []


def decode_mountinfo_path(raw: str) -> str:
    """Decode octal escape sequences in mountinfo mount/source fields."""
    out: list[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 3 < len(raw):
            esc = raw[i + 1 : i + 4]
            if esc in ("040", "011", "012", "134"):
                out.append(
                    {
                        "040": " ",
                        "011": "\t",
                        "012": "\n",
                        "134": "\\",
                    }[esc]
                )
                i += 4
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def strict_mount_proof(root: str) -> tuple[bool, str, dict[str, str]]:
    """True only when root is the exact mount point of a block-device mount."""
    target = os.path.realpath(root)
    facts: dict[str, str] = {"root": target}
    for line in _read_mountinfo():
        parts = line.split()
        if len(parts) < 10:
            continue
        # mountinfo: ... mount_point ... - fstype source ...
        try:
            dash_idx = parts.index("-")
        except ValueError:
            continue
        mount_point = decode_mountinfo_path(parts[4])
        if mount_point != target:
            continue
        fstype = parts[dash_idx + 1] if dash_idx + 1 < len(parts) else ""
        source = parts[dash_idx + 2] if dash_idx + 2 < len(parts) else ""
        facts["mount_point"] = mount_point
        facts["fstype"] = fstype
        facts["source"] = source
        if fstype in _DISALLOWED_MOUNT_FSTYPES:
            return False, f"disallowed_fstype:{fstype}", facts
        if not source.startswith("/dev/"):
            return False, f"source_not_block_dev:{source}", facts
        return True, "", facts
    return False, "no_exact_mount_entry", facts


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


def has_local_volume_data(*, for_volume_bootstrap: bool = False) -> bool:
    """True when soul_map, pump ladder, or a non-trivial message_intel DB is present."""
    root = _data_dir()
    if not os.path.isdir(root):
        return False
    markers: tuple[str, ...] = (
        "soul_map.json",
        "pump_ladder.json",
        os.path.join("pump_desk", "latest.json"),
    )
    if not for_volume_bootstrap:
        markers = (".worker_heartbeat",) + markers
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
