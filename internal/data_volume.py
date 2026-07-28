"""Detect whether this process can read committed JSON/SQLite on the Fly volume."""

from __future__ import annotations

import os


def _data_dir() -> str:
    return os.environ.get("DATA_DIR", "data")


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


def needs_worker_volume_proxy() -> bool:
    """split_v2 web — always proxy volume-backed APIs to the worker machine."""
    from internal.run_mode import is_worker_mode, split_worker_v2_enabled

    return split_worker_v2_enabled() and not is_worker_mode()
