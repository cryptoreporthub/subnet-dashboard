"""
File utilities for safe file operations in serverless environments.

Ensures data directory exists before file writes to prevent
"No such file or directory" errors on Fly.io and similar platforms.
"""

import json
import logging
import os
import tempfile
from typing import Any, Dict, Optional, Tuple


DATA_DIR = os.environ.get("DATA_DIR", "data")

_logger = logging.getLogger(__name__)
_data_dir_created_logged = False
_fsync_dir_warned = False


def ensure_data_dir() -> str:
    """Ensure the data directory exists and return its path.

    On Fly.io the root filesystem is ephemeral and ``data/`` is only present
    when a persistent volume is mounted (see fly.toml ``[mounts]``). If the
    directory is missing at write time the background schedulers silently fail,
    so every write path calls this before touching disk. The "created" event
    is logged once per process so a missing volume is visible in the app logs.
    """
    global _data_dir_created_logged
    try:
        if not os.path.isdir(DATA_DIR):
            os.makedirs(DATA_DIR, exist_ok=True)
            _logger.info("data/ directory missing, created at %s", DATA_DIR)
            _data_dir_created_logged = True
    except Exception as exc:
        _logger.warning("Could not create data directory %s: %s", DATA_DIR, exc)
    return DATA_DIR


def _fsync_dir(dir_name: str) -> None:
    """Persist a rename by fsyncing its directory (POSIX; no-op on Windows).

    Best-effort after a successful replace: data is already committed; callers
    should not treat a directory fsync failure as a failed write.
    """
    global _fsync_dir_warned
    if os.name == "nt":
        return
    try:
        dfd = os.open(dir_name, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError as exc:
        if not _fsync_dir_warned:
            _logger.warning("Could not fsync directory %s: %s", dir_name, exc)
            _fsync_dir_warned = True


def safe_write_json(
    path: str,
    data: Dict[str, Any],
    *,
    indent: Optional[int] = 2,
    separators: Optional[Tuple[str, str]] = None,
) -> None:
    """
    Write JSON data to a file atomically and durably, with directory creation.

    Each writer gets a pid-tagged mkstemp sidecar ``<basename>.<pid>.<rand>.tmp``
    so the reaper can skip live owners; stale temps are reaped by
    ``internal.tmp_boot_reaper``. Never use mkstemp with suffix ``.json`` alone.

    The temp file is fsynced before ``os.replace`` so a crash cannot leave the
    target pointing at empty or partial content, and the directory is fsynced
    after so the rename itself survives power loss.
    """
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        dir=dir_name or ".",
        prefix=f"{os.path.basename(path)}.{os.getpid()}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            dump_kw: Dict[str, Any] = {}
            if separators is not None:
                dump_kw["separators"] = separators
            if indent is not None:
                dump_kw["indent"] = indent
            json.dump(data, f, **dump_kw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
        _fsync_dir(dir_name or ".")
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def safe_read_json(path: str, default: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Read JSON from a file, returning default if missing or invalid.
    """
    if default is None:
        default = {}
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return default