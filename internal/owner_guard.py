"""Single-writer step 1: process write-owner lock + same-volume marker proof.

Later migration steps call owner_guard() before persisting. Reads are unaffected.
Do not infer write authority from RUN_MODE or env alone.
"""

from __future__ import annotations

import atexit
import errno
import fcntl
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from internal.data_volume import has_local_volume_data, resolved_data_dir
from internal.file_utils import ensure_data_dir

logger = logging.getLogger(__name__)

WRITE_OWNER_LOCK_NAME = ".write_owner.lock"
VOLUME_MARKER_NAME = ".data_volume_marker.json"
_MARKER_VERSION = 1

_owner_lock_fd: Optional[int] = None
_write_owner_lock_held = False


class WriteRefused(Exception):
    """Raised when owner_guard refuses a write (fail closed)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class OwnerGuardState:
    lock_held: bool
    volume_ok: bool
    reason: str
    prod_like: bool

    @property
    def writes_allowed(self) -> bool:
        return self.lock_held and self.volume_ok


def volume_check_prod_like() -> bool:
    """True when this process must prove the persistent DATA_DIR volume (not bypassable in tests)."""
    if os.environ.get("FLY_APP_NAME", "").strip():
        return True
    flag = os.environ.get("DATA_DIR_IS_VOLUME", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    from internal.data_volume import data_dir_is_mounted_volume

    return data_dir_is_mounted_volume()


def _owner_guard_skip_allowed() -> bool:
    if volume_check_prod_like():
        return False
    return os.environ.get("OWNER_GUARD_SKIP", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def data_dir_fingerprint() -> str:
    root = resolved_data_dir()
    st = os.stat(root)
    return f"{st.st_dev}:{st.st_ino}"


def volume_marker_path() -> str:
    return os.path.join(resolved_data_dir(), VOLUME_MARKER_NAME)


def write_owner_lock_path() -> str:
    return os.path.join(resolved_data_dir(), WRITE_OWNER_LOCK_NAME)


def _read_volume_marker() -> Optional[Dict[str, Any]]:
    path = volume_marker_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _write_volume_marker(fingerprint: str) -> None:
    ensure_data_dir()
    path = volume_marker_path()
    payload = {"version": _MARKER_VERSION, "fingerprint": fingerprint}
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


def _abort_lock_acquire(fd: int) -> None:
    """Release a lock fd acquired in try_acquire_write_owner_lock (fail closed)."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def _prod_volume_marker_bootstrap_allowed() -> bool:
    """Fly/existing volume: safe one-time marker when committed data already on disk."""
    from internal.data_volume import data_dir_is_mounted_volume

    if not volume_check_prod_like():
        return False
    if not data_dir_is_mounted_volume():
        return False
    return has_local_volume_data()


def volume_marker_status() -> tuple[bool, str]:
    """Same-volume proof via marker fingerprint on DATA_DIR."""
    try:
        fingerprint = data_dir_fingerprint()
    except OSError as exc:
        return False, f"volume_marker_check_error:{exc}"

    marker = _read_volume_marker()
    if marker is None:
        if _prod_volume_marker_bootstrap_allowed():
            try:
                _write_volume_marker(fingerprint)
                logger.info(
                    "owner_guard: bootstrapped volume marker on existing data volume at %s",
                    volume_marker_path(),
                )
            except OSError as exc:
                return False, f"volume_marker_create_failed:{exc}"
            return True, ""
        if volume_check_prod_like():
            return False, "volume_marker_missing"
        try:
            _write_volume_marker(fingerprint)
            logger.info(
                "owner_guard: created dev volume marker at %s", volume_marker_path()
            )
        except OSError as exc:
            return False, f"volume_marker_create_failed:{exc}"
        return True, ""

    expected = marker.get("fingerprint")
    if not isinstance(expected, str) or not expected:
        return False, "volume_marker_invalid"
    if expected != fingerprint:
        return False, "volume_marker_fingerprint_mismatch"
    return True, ""


def inspect_owner_guard() -> OwnerGuardState:
    prod_like = volume_check_prod_like()
    if _owner_guard_skip_allowed():
        return OwnerGuardState(
            lock_held=True,
            volume_ok=True,
            reason="owner_guard_skip_dev",
            prod_like=prod_like,
        )
    vol_ok, vol_reason = volume_marker_status()
    if not _write_owner_lock_held:
        reason = vol_reason if not vol_ok else "write_owner_lock_not_held"
        return OwnerGuardState(
            lock_held=False,
            volume_ok=vol_ok,
            reason=reason,
            prod_like=prod_like,
        )
    reason = "" if vol_ok else vol_reason
    return OwnerGuardState(
        lock_held=True,
        volume_ok=vol_ok,
        reason=reason,
        prod_like=prod_like,
    )


def owner_guard_reason() -> Optional[str]:
    """None when writes are allowed; otherwise a stable log/API reason string."""
    state = inspect_owner_guard()
    if state.writes_allowed:
        return None
    return state.reason or "write_refused"


def owner_guard(*, operation: str = "write") -> None:
    """Fail closed when this process is not the confirmed volume write owner."""
    reason = owner_guard_reason()
    if reason is None:
        return
    logger.warning(
        "owner_guard refused %s: %s (lock_held=%s prod_like=%s)",
        operation,
        reason,
        _write_owner_lock_held,
        volume_check_prod_like(),
    )
    raise WriteRefused(reason)


def _release_write_owner_lock() -> None:
    global _owner_lock_fd, _write_owner_lock_held
    fd = _owner_lock_fd
    _owner_lock_fd = None
    _write_owner_lock_held = False
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def try_acquire_write_owner_lock() -> tuple[bool, str]:
    """Non-blocking exclusive lock on DATA_DIR; kept until process exit."""
    global _owner_lock_fd, _write_owner_lock_held
    if _owner_guard_skip_allowed():
        _write_owner_lock_held = True
        return True, "owner_guard_skip_dev"
    if _write_owner_lock_held:
        return True, ""

    ensure_data_dir()
    path = write_owner_lock_path()
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError as exc:
        logger.error("owner_guard: cannot open lock file %s: %s", path, exc)
        return False, f"write_owner_lock_open_failed:{exc}"

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        logger.error(
            "owner_guard: another process holds %s — writes will be refused",
            path,
        )
        return False, "write_owner_lock_contended"
    except OSError as exc:
        os.close(fd)
        if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
            logger.error(
                "owner_guard: another process holds %s — writes will be refused",
                path,
            )
            return False, "write_owner_lock_contended"
        logger.error("owner_guard: flock failed on %s: %s", path, exc)
        return False, f"write_owner_lock_error:{exc}"

    try:
        vol_ok, vol_reason = volume_marker_status()
    except OSError as exc:
        _abort_lock_acquire(fd)
        logger.error("owner_guard: volume check raised (%s) — lock released", exc)
        return False, f"volume_marker_check_error:{exc}"
    except Exception as exc:
        _abort_lock_acquire(fd)
        logger.error("owner_guard: volume check failed (%s) — lock released", exc)
        return False, f"volume_marker_check_error:{exc}"

    if not vol_ok:
        _abort_lock_acquire(fd)
        logger.error("owner_guard: volume check failed (%s) — writes refused", vol_reason)
        return False, vol_reason

    _owner_lock_fd = fd
    _write_owner_lock_held = True
    atexit.register(_release_write_owner_lock)
    logger.info("owner_guard: write owner lock acquired on %s", path)
    return True, ""


def acquire_write_owner_at_worker_startup() -> bool:
    """Worker entry: take exclusive lock + volume proof, or fail closed (no writers)."""
    ok, detail = try_acquire_write_owner_lock()
    if ok:
        return True
    logger.error(
        "owner_guard: worker startup blocked (%s) — background writers will not start",
        detail,
    )
    return False


def reset_owner_guard_for_tests() -> None:
    """Test-only teardown hook."""
    _release_write_owner_lock()
