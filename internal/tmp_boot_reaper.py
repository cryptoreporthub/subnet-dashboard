"""Reap stale atomic-write .tmp files on the Fly data volume at worker boot."""

from __future__ import annotations

import fcntl
import logging
import os
import re
import time
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Grace at worker boot so concurrent startup writers are not unlinked mid-write.
_BOOT_REAP_MIN_AGE_SECONDS = 60

# mkstemp(prefix="tmp") orphans: tmp + 8 of [a-z0-9_] + .json or .tmp (legacy whale writer).
_LEGACY_ORPHAN_RE = re.compile(r"^tmp[a-z0-9_]{8}\.(?:json|tmp)$")


def _data_dir() -> str:
    root = os.environ.get("DATA_DIR", "data")
    if os.path.isabs(root):
        return root
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, root)


def _min_age_seconds() -> int:
    raw = os.environ.get("TMP_BOOT_REAP_MIN_AGE_SECONDS", "3600").strip()
    try:
        return max(60, int(raw))
    except ValueError:
        return 3600


def _volume_mount_verified() -> bool:
    """Fail closed: do not reap without a positive mounted-volume signal."""
    try:
        from internal.data_volume import data_dir_is_mounted_volume

        return data_dir_is_mounted_volume()
    except Exception as exc:
        logger.warning("tmp boot reaper: volume check failed, skipping: %s", exc)
        return False


def _temp_file_in_use(path: str) -> bool:
    """True when another process holds an exclusive flock on the temp file."""
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return True
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
        except BlockingIOError:
            return True
    finally:
        os.close(fd)
    return False


def _is_reap_candidate(filename: str) -> bool:
    if _LEGACY_ORPHAN_RE.match(filename):
        return True
    if filename.endswith(".tmp"):
        return True
    return False


def find_stale_tmp_files(*, data_dir: str | None = None, min_age_seconds: int | None = None) -> List[str]:
    """Return paths to stale temp/orphan files older than min_age under data_dir."""
    root = data_dir or _data_dir()
    if not os.path.isdir(root):
        return []
    cutoff = time.time() - (min_age_seconds if min_age_seconds is not None else _min_age_seconds())
    stale: List[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not _is_reap_candidate(name):
                continue
            path = os.path.join(dirpath, name)
            try:
                if os.path.getmtime(path) <= cutoff:
                    stale.append(path)
            except OSError:
                continue
    return stale


def reap_stale_tmp_files(
    *, dry_run: bool = False, min_age_seconds: int | None = None
) -> Tuple[int, List[str]]:
    """Delete stale temp/orphan files; return (removed_count, paths)."""
    paths = find_stale_tmp_files(min_age_seconds=min_age_seconds)
    removed: List[str] = []
    total_bytes = 0
    for path in paths:
        try:
            total_bytes += os.path.getsize(path)
        except OSError:
            pass
        if dry_run:
            removed.append(path)
            continue
        if _temp_file_in_use(path):
            logger.debug("tmp boot reaper: skip in-use temp %s", path)
            continue
        try:
            os.unlink(path)
            removed.append(path)
        except OSError as exc:
            logger.warning("tmp boot reaper: failed to remove %s: %s", path, exc)
    if removed:
        logger.info(
            "tmp boot reaper: %s %d stale temp file(s) (%d bytes)",
            "would remove" if dry_run else "removed",
            len(removed),
            total_bytes,
        )
    return len(removed), removed


def maybe_reap_at_machine_start() -> None:
    """Once per container start (fly entrypoint), before web/worker can write."""
    flag = os.environ.get("TMP_BOOT_REAP", "on").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return
    if not _volume_mount_verified():
        return
    reap_stale_tmp_files(min_age_seconds=_BOOT_REAP_MIN_AGE_SECONDS)


def maybe_reap_at_boot() -> None:
    """Run on dedicated worker boot only (inline worker defers to machine-start reap)."""
    flag = os.environ.get("TMP_BOOT_REAP", "on").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return
    from internal.run_mode import inline_worker_expected, is_worker_mode

    if not is_worker_mode():
        return
    if inline_worker_expected():
        return
    if not _volume_mount_verified():
        return
    reap_stale_tmp_files(min_age_seconds=_BOOT_REAP_MIN_AGE_SECONDS)


def maybe_reap_scheduled() -> None:
    """Hourly sweep on worker (same gates as boot reaper)."""
    flag = os.environ.get("TMP_BOOT_REAP", "on").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return
    from internal.run_mode import is_worker_mode

    if not is_worker_mode():
        return
    if not _volume_mount_verified():
        return
    reap_stale_tmp_files()
