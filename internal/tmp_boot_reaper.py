"""Reap stale atomic-write .tmp files on the Fly data volume at worker boot."""

from __future__ import annotations

import logging
import os
import re
import time
from typing import List, Tuple

logger = logging.getLogger(__name__)

_BOOT_REAP_MIN_AGE_SECONDS = 60
_PID_REUSE_CAP_SECONDS = 6 * 3600

# mkstemp(prefix="tmp") orphans: tmp + 8 of [a-z0-9_] + .json or .tmp (legacy whale writer).
_LEGACY_ORPHAN_RE = re.compile(r"^tmp[a-z0-9_]{8}\.(?:json|tmp)$")
# safe_write_json: <basename>.<pid>.<random>.tmp
_PID_SIDECAR_RE = re.compile(r"^(.+)\.(\d+)\.[a-z0-9_]+\.tmp$", re.IGNORECASE)


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


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True


def _is_reap_candidate(filename: str) -> bool:
    if _LEGACY_ORPHAN_RE.match(filename):
        return True
    if _PID_SIDECAR_RE.match(filename):
        return True
    if filename.endswith(".tmp"):
        return True
    return False


def _should_reap(
    filename: str,
    mtime: float,
    *,
    now: float,
    min_age_seconds: int,
    at_boot: bool,
) -> bool:
    age = now - mtime
    pid_match = _PID_SIDECAR_RE.match(filename)
    if pid_match:
        pid = int(pid_match.group(2))
        if not _process_alive(pid):
            return True
        if age >= _PID_REUSE_CAP_SECONDS:
            return True
        return False
    if _LEGACY_ORPHAN_RE.match(filename):
        return age >= min_age_seconds
    if filename.endswith(".tmp"):
        if at_boot:
            return False
        return age >= min_age_seconds
    return False


def find_stale_tmp_files(
    *,
    data_dir: str | None = None,
    min_age_seconds: int | None = None,
    at_boot: bool = False,
) -> List[str]:
    """Return paths to stale temp/orphan files under data_dir."""
    root = data_dir or _data_dir()
    if not os.path.isdir(root):
        return []
    floor = min_age_seconds if min_age_seconds is not None else _min_age_seconds()
    now = time.time()
    stale: List[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not _is_reap_candidate(name):
                continue
            path = os.path.join(dirpath, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if _should_reap(name, mtime, now=now, min_age_seconds=floor, at_boot=at_boot):
                stale.append(path)
    return stale


def reap_stale_tmp_files(
    *,
    dry_run: bool = False,
    min_age_seconds: int | None = None,
    at_boot: bool = False,
) -> Tuple[int, List[str]]:
    """Delete stale temp/orphan files; return (removed_count, paths)."""
    paths = find_stale_tmp_files(min_age_seconds=min_age_seconds, at_boot=at_boot)
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


def run_machine_start_reap(*, dry_run: bool = False) -> Tuple[int, List[str]]:
    """Entrypoint / CLI machine-start reap (honors TMP_BOOT_REAP + volume probe)."""
    flag = os.environ.get("TMP_BOOT_REAP", "on").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return 0, []
    if not _volume_mount_verified():
        return 0, []
    return reap_stale_tmp_files(
        dry_run=dry_run,
        min_age_seconds=_BOOT_REAP_MIN_AGE_SECONDS,
        at_boot=True,
    )


def maybe_reap_at_machine_start() -> None:
    """Once per container start (fly entrypoint), before web/worker can write."""
    run_machine_start_reap()


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
    reap_stale_tmp_files(min_age_seconds=_BOOT_REAP_MIN_AGE_SECONDS, at_boot=True)


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
    reap_stale_tmp_files(at_boot=False)
