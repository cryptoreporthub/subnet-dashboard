"""Reap stale atomic-write .tmp files on the Fly data volume at worker boot."""

from __future__ import annotations

import logging
import os
import time
from typing import List, Tuple

logger = logging.getLogger(__name__)


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


def find_stale_tmp_files(*, data_dir: str | None = None, min_age_seconds: int | None = None) -> List[str]:
    """Return paths to .tmp files older than min_age under data_dir."""
    root = data_dir or _data_dir()
    if not os.path.isdir(root):
        return []
    cutoff = time.time() - (min_age_seconds if min_age_seconds is not None else _min_age_seconds())
    stale: List[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not name.endswith(".tmp"):
                continue
            path = os.path.join(dirpath, name)
            try:
                if os.path.getmtime(path) <= cutoff:
                    stale.append(path)
            except OSError:
                continue
    return stale


def reap_stale_tmp_files(*, dry_run: bool = False) -> Tuple[int, List[str]]:
    """Delete stale .tmp files; return (removed_count, paths)."""
    paths = find_stale_tmp_files()
    removed: List[str] = []
    for path in paths:
        if dry_run:
            removed.append(path)
            continue
        try:
            os.unlink(path)
            removed.append(path)
        except OSError as exc:
            logger.warning("tmp boot reaper: failed to remove %s: %s", path, exc)
    if removed:
        logger.info(
            "tmp boot reaper: %s %d stale .tmp file(s)",
            "would remove" if dry_run else "removed",
            len(removed),
        )
    return len(removed), removed


def maybe_reap_at_boot() -> None:
    """Run once on worker boot when enabled (default on worker with volume)."""
    flag = os.environ.get("TMP_BOOT_REAP", "on").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return
    from internal.run_mode import is_worker_mode

    if not is_worker_mode():
        return
    try:
        from internal.data_volume import data_dir_is_mounted_volume

        if not data_dir_is_mounted_volume():
            return
    except Exception:
        pass
    reap_stale_tmp_files()
