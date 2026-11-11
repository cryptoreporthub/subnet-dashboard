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
import secrets
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from internal.data_volume import (
    has_local_volume_data,
    resolved_data_dir,
    strict_mount_proof,
)

logger = logging.getLogger(__name__)

VOLUME_PIN_MISSING_HINT = "volume_pin_missing: set DATA_VOLUME_ID (see DEPLOY.md)"

WRITE_OWNER_LOCK_NAME = ".write_owner.lock"
VOLUME_MARKER_NAME = ".data_volume_marker.json"
_MARKER_VERSION = 2
_MARKER_TMP_MAX_AGE_SEC = 3600

_owner_lock_fd: Optional[int] = None
_pending_lock_fd: Optional[int] = None
_write_owner_lock_held = False
_owner_pid: Optional[int] = None
_owner_root: Optional[str] = None
_marker_stat_at_acquire: Optional[Tuple[int, int]] = None
_lock_path_inode_at_acquire: Optional[int] = None
_terminal_owner_lost = False
_terminal_exit_scheduled = False
_acquiring = False
_acquire_rlock = threading.RLock()
_after_flock_hook: Optional[Callable[[], None]] = None
_atexit_registered = False
_skip_dev_active = False


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
    """True when this process must prove the persistent DATA_DIR volume."""
    if os.environ.get("FLY_APP_NAME", "").strip():
        return True
    root = resolved_data_dir()
    ok, _, _ = strict_mount_proof(root)
    return ok


def _owner_guard_skip_allowed() -> bool:
    if volume_check_prod_like():
        return False
    return os.environ.get("OWNER_GUARD_SKIP", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _owner_data_root() -> str:
    return os.path.realpath(resolved_data_dir())


def volume_marker_path(root: Optional[str] = None) -> str:
    base = root if root is not None else _owner_data_root()
    return os.path.join(base, VOLUME_MARKER_NAME)


def write_owner_lock_path(root: Optional[str] = None) -> str:
    base = root if root is not None else _owner_data_root()
    return os.path.join(base, WRITE_OWNER_LOCK_NAME)


def _pinned_volume_id_from_env() -> Optional[str]:
    raw = os.environ.get("DATA_VOLUME_ID", "").strip()
    return raw or None


def _fly_app_name() -> str:
    return os.environ.get("FLY_APP_NAME", "").strip()


def _fly_machine_id() -> str:
    return os.environ.get("FLY_MACHINE_ID", "").strip()


def _read_marker_json(path: str) -> Tuple[str, Optional[Dict[str, Any]], str]:
    """Classify marker file without writing. Returns (state, payload|None, detail)."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return "ABSENT", None, ""
    except OSError as exc:
        return "UNREADABLE", None, str(exc)
    if not os.path.isfile(path) or os.path.islink(path):
        return "CORRUPT", None, "not_regular_file"
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        return "UNREADABLE", None, str(exc)
    try:
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError as exc:
        return "UNREADABLE", None, str(exc)
    if not raw.strip():
        return "CORRUPT", None, "empty"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return "CORRUPT", None, "json_decode"
    if not isinstance(payload, dict):
        return "CORRUPT", None, "not_object"
    if payload.get("version") != _MARKER_VERSION:
        return "CORRUPT", None, "bad_version"
    volume_id = payload.get("volume_id")
    if not isinstance(volume_id, str) or len(volume_id) != 32:
        return "CORRUPT", None, "bad_volume_id"
    try:
        int(volume_id, 16)
    except ValueError:
        return "CORRUPT", None, "bad_volume_id"
    app_name = payload.get("app_name")
    if not isinstance(app_name, str):
        return "CORRUPT", None, "bad_app_name"
    pinned = payload.get("pinned_volume_id")
    if pinned is not None and not isinstance(pinned, str):
        return "CORRUPT", None, "bad_pinned_volume_id"
    fly = _fly_app_name()
    if fly and app_name != fly:
        return "MISMATCH", payload, "app_name"
    env_pin = _pinned_volume_id_from_env()
    marker_pin = pinned if isinstance(pinned, str) else ""
    if env_pin and marker_pin != env_pin:
        return "MISMATCH", payload, "pinned_volume_id"
    exclusive = payload.get("exclusive_machine_id")
    machine = _fly_machine_id()
    if machine:
        if not isinstance(exclusive, str) or not exclusive:
            return "MISMATCH", payload, "exclusive_machine_id_missing"
        if exclusive != machine:
            return "MISMATCH", payload, "exclusive_machine_id"
    return "VALID", payload, ""


def _classify_marker(root: str) -> Tuple[str, Optional[Dict[str, Any]], str]:
    return _read_marker_json(volume_marker_path(root))


def _cleanup_stale_marker_temps(root: str) -> None:
    marker = volume_marker_path(root)
    prefix = f"{marker}."
    suffix = ".tmp"
    now = time.time()
    try:
        for name in os.listdir(root):
            if not name.startswith(os.path.basename(prefix)) or not name.endswith(suffix):
                continue
            path = os.path.join(root, name)
            try:
                if now - os.path.getmtime(path) > _MARKER_TMP_MAX_AGE_SEC:
                    os.unlink(path)
            except OSError:
                pass
    except OSError:
        pass


def _bootstrap_marker_payload() -> Dict[str, Any]:
    fly = _fly_app_name()
    pin = _pinned_volume_id_from_env()
    payload: Dict[str, Any] = {
        "version": _MARKER_VERSION,
        "volume_id": uuid.uuid4().hex,
        "app_name": fly,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if pin:
        payload["pinned_volume_id"] = pin
    machine = _fly_machine_id()
    if machine:
        payload["exclusive_machine_id"] = machine
    return payload


def _bootstrap_volume_marker(root: str) -> Tuple[bool, str]:
    _cleanup_stale_marker_temps(root)
    marker_path = volume_marker_path(root)
    payload = _bootstrap_marker_payload()
    tmp = f"{marker_path}.{secrets.token_hex(8)}.tmp"
    tmp_fd: Optional[int] = None
    try:
        tmp_fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            tmp_fd = None
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, marker_path)
        except FileExistsError:
            state, _, detail = _classify_marker(root)
            if state == "VALID":
                return True, ""
            return False, f"marker_bootstrap_race:{state}:{detail}"
        os.unlink(tmp)
        tmp = ""
        dir_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        state, _, detail = _classify_marker(root)
        if state == "VALID":
            return True, ""
        return False, f"marker_bootstrap_verify_failed:{state}:{detail}"
    except OSError as exc:
        return False, f"marker_bootstrap_failed:{exc}"
    finally:
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _abort_lock_acquire(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def _forget_inherited_owner() -> None:
    global _owner_lock_fd, _pending_lock_fd, _write_owner_lock_held, _owner_pid
    global _owner_root, _marker_stat_at_acquire, _lock_path_inode_at_acquire
    for fd in (_pending_lock_fd, _owner_lock_fd):
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
    _owner_lock_fd = None
    _pending_lock_fd = None
    _write_owner_lock_held = False
    _owner_pid = None
    _owner_root = None
    _marker_stat_at_acquire = None
    _lock_path_inode_at_acquire = None
    _skip_dev_active = False


def _release_write_owner_lock() -> None:
    global _owner_lock_fd, _write_owner_lock_held, _owner_pid
    global _marker_stat_at_acquire, _lock_path_inode_at_acquire
    global _terminal_owner_lost, _skip_dev_active
    fd = _owner_lock_fd
    pid = _owner_pid
    _owner_lock_fd = None
    _write_owner_lock_held = False
    _owner_pid = None
    _marker_stat_at_acquire = None
    _lock_path_inode_at_acquire = None
    _skip_dev_active = False
    if fd is None:
        return
    if pid is not None and os.getpid() != pid:
        try:
            os.close(fd)
        except OSError:
            pass
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def _fork_before() -> None:
    _acquire_rlock.acquire()


def _fork_after_in_child() -> None:
    _forget_inherited_owner()
    try:
        _acquire_rlock.release()
    except RuntimeError:
        pass


def _fork_after_in_parent() -> None:
    """Release the RLock ``_fork_before`` acquired in the parent after fork.

    Without this, a fork from a non-main thread leaves that thread holding
    ``_acquire_rlock``, which can block interpreter shutdown.
    """
    try:
        _acquire_rlock.release()
    except RuntimeError:
        pass


os.register_at_fork(
    before=_fork_before,
    after_in_parent=_fork_after_in_parent,
    after_in_child=_fork_after_in_child,
)


def _schedule_terminal_exit() -> None:
    global _terminal_exit_scheduled
    if _terminal_exit_scheduled:
        return
    _terminal_exit_scheduled = True

    def _exit() -> None:
        logger.error(
            "owner_guard: terminal owner_lost — exiting 3 for supervisor restart"
        )
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        os._exit(3)

    threading.Thread(target=_exit, daemon=True, name="owner-guard-exit").start()


def _owner_invariants_reason(root: str) -> Optional[str]:
    global _terminal_owner_lost
    if _terminal_owner_lost:
        return "owner_lost:terminal"
    if not _write_owner_lock_held or _owner_lock_fd is None:
        return "write_owner_lock_not_held"
    if _owner_pid is not None and os.getpid() != _owner_pid:
        return "owner_pid_mismatch"
    lock_path = write_owner_lock_path(root)
    try:
        lock_st = os.stat(lock_path)
        lock_fd_st = os.fstat(_owner_lock_fd)
    except OSError as exc:
        _terminal_owner_lost = True
        _schedule_terminal_exit()
        return f"owner_lost:lock_stat:{exc}"
    if lock_fd_st.st_nlink <= 0:
        _terminal_owner_lost = True
        _schedule_terminal_exit()
        return "owner_lost:lock_unlinked"
    if _lock_path_inode_at_acquire is not None and lock_st.st_ino != _lock_path_inode_at_acquire:
        _terminal_owner_lost = True
        _schedule_terminal_exit()
        return "owner_lost:lock_replaced"
    if lock_st.st_ino != lock_fd_st.st_ino:
        _terminal_owner_lost = True
        _schedule_terminal_exit()
        return "owner_lost:lock_inode_mismatch"
    marker_path = volume_marker_path(root)
    try:
        mst = os.stat(marker_path)
    except OSError as exc:
        _terminal_owner_lost = True
        _schedule_terminal_exit()
        return f"owner_lost:marker_stat:{exc}"
    if _marker_stat_at_acquire is not None:
        cur = (mst.st_ino, mst.st_mtime_ns, mst.st_size)
        if cur != _marker_stat_at_acquire:
            _terminal_owner_lost = True
            _schedule_terminal_exit()
            return "owner_lost:marker_changed"
    return None


def inspect_owner_guard() -> OwnerGuardState:
    prod_like = volume_check_prod_like()
    if _skip_dev_active and _owner_pid == os.getpid():
        return OwnerGuardState(
            lock_held=True,
            volume_ok=True,
            reason="owner_guard_skip_dev",
            prod_like=prod_like,
        )
    if _owner_guard_skip_allowed() and not _write_owner_lock_held:
        return OwnerGuardState(
            lock_held=False,
            volume_ok=False,
            reason="write_owner_lock_not_held",
            prod_like=prod_like,
        )
    if not _write_owner_lock_held:
        return OwnerGuardState(
            lock_held=False,
            volume_ok=False,
            reason="write_owner_lock_not_held",
            prod_like=prod_like,
        )
    root = _owner_root or _owner_data_root()
    inv = _owner_invariants_reason(root)
    if inv:
        return OwnerGuardState(
            lock_held=True,
            volume_ok=False,
            reason=inv,
            prod_like=prod_like,
        )
    return OwnerGuardState(
        lock_held=True,
        volume_ok=True,
        reason="",
        prod_like=prod_like,
    )


def owner_guard_reason() -> Optional[str]:
    state = inspect_owner_guard()
    if state.writes_allowed:
        return None
    return state.reason or "write_refused"


def owner_guard(*, operation: str = "write") -> None:
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


def _open_write_lock(root: str) -> Tuple[Optional[int], str]:
    path = write_owner_lock_path(root)
    try:
        lst = os.lstat(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        return None, f"write_owner_lock_open_failed:{exc}"
    else:
        if not os.path.isfile(path) or os.path.islink(path):
            return None, "lock_not_regular"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o644)
    except OSError as exc:
        return None, f"write_owner_lock_open_failed:{exc}"
    try:
        lst = os.lstat(path)
        if not os.path.isfile(path) or os.path.islink(path):
            os.close(fd)
            return None, "lock_not_regular"
    except OSError as exc:
        os.close(fd)
        return None, f"write_owner_lock_open_failed:{exc}"
    return fd, ""


def try_acquire_write_owner_lock() -> tuple[bool, str]:
    global _owner_lock_fd, _pending_lock_fd, _write_owner_lock_held, _owner_pid
    global _owner_root, _marker_stat_at_acquire, _lock_path_inode_at_acquire
    global _acquiring, _atexit_registered, _skip_dev_active

    with _acquire_rlock:
        _acquiring = True
        held_fd: Optional[int] = None
        try:
            if _owner_guard_skip_allowed():
                _skip_dev_active = True
                _write_owner_lock_held = True
                _owner_pid = os.getpid()
                return True, "owner_guard_skip_dev"
            if _write_owner_lock_held:
                root = _owner_root or _owner_data_root()
                inv = _owner_invariants_reason(root)
                if inv:
                    return False, inv
                return True, ""

            prod_like = volume_check_prod_like()
            root = _owner_data_root()
            if prod_like:
                if not os.path.isdir(root):
                    return False, "data_dir_missing"
            else:
                os.makedirs(root, exist_ok=True)

            fd, open_err = _open_write_lock(root)
            if fd is None:
                logger.error("owner_guard: cannot open lock file: %s", open_err)
                return False, open_err

            global _pending_lock_fd
            _pending_lock_fd = fd
            held_fd = fd
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                _pending_lock_fd = None
                held_fd = None
                return False, "write_owner_lock_contended"
            except OSError as exc:
                os.close(fd)
                _pending_lock_fd = None
                held_fd = None
                if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                    return False, "write_owner_lock_contended"
                return False, f"write_owner_lock_error:{exc}"

            if _after_flock_hook is not None:
                _after_flock_hook()

            _pending_lock_fd = None

            if prod_like:
                ok, why, _facts = strict_mount_proof(root)
                if not ok:
                    _abort_lock_acquire(fd)
                    held_fd = None
                    return False, f"mount_unproven:{why}"

            if prod_like and not _pinned_volume_id_from_env():
                _abort_lock_acquire(fd)
                held_fd = None
                return False, "volume_pin_missing"

            state, _payload, detail = _classify_marker(root)
            if state == "ABSENT":
                if prod_like and not has_local_volume_data(for_volume_bootstrap=True):
                    _abort_lock_acquire(fd)
                    held_fd = None
                    return False, "marker_absent_no_data"
                boot_ok, boot_detail = _bootstrap_volume_marker(root)
                if not boot_ok:
                    _abort_lock_acquire(fd)
                    held_fd = None
                    return False, boot_detail
            elif state in ("UNREADABLE", "CORRUPT"):
                _abort_lock_acquire(fd)
                held_fd = None
                return False, f"marker_{state.lower()}"
            elif state == "MISMATCH":
                _abort_lock_acquire(fd)
                held_fd = None
                return False, f"marker_mismatch:{detail}"
            elif state != "VALID":
                _abort_lock_acquire(fd)
                held_fd = None
                return False, f"marker_unknown:{state}"

            state2, _, _ = _classify_marker(root)
            if state2 != "VALID":
                _abort_lock_acquire(fd)
                held_fd = None
                return False, "marker_bootstrap_verify_failed"

            try:
                lock_st = os.stat(write_owner_lock_path(root))
                marker_st = os.stat(volume_marker_path(root))
            except OSError as exc:
                _abort_lock_acquire(fd)
                held_fd = None
                return False, f"volume_marker_check_error:{exc}"

            _owner_lock_fd = fd
            held_fd = None
            _write_owner_lock_held = True
            _owner_pid = os.getpid()
            _owner_root = root
            _lock_path_inode_at_acquire = lock_st.st_ino
            _marker_stat_at_acquire = (
                marker_st.st_ino,
                marker_st.st_mtime_ns,
                marker_st.st_size,
            )
            if not _atexit_registered:
                atexit.register(_release_write_owner_lock)
                _atexit_registered = True
            logger.info(
                "owner_guard: write owner lock acquired on %s",
                write_owner_lock_path(root),
            )
            return True, ""
        except OSError as exc:
            if held_fd is not None and _owner_lock_fd is None:
                _abort_lock_acquire(held_fd)
            if _pending_lock_fd is not None:
                _abort_lock_acquire(_pending_lock_fd)
                _pending_lock_fd = None
            return False, f"volume_check_error:{exc}"
        except Exception as exc:
            if held_fd is not None and _owner_lock_fd is None:
                _abort_lock_acquire(held_fd)
            if _pending_lock_fd is not None:
                _abort_lock_acquire(_pending_lock_fd)
                _pending_lock_fd = None
            return False, f"volume_check_error:{exc}"
        finally:
            _acquiring = False


def _log_volume_pin_missing_hint(detail: str) -> None:
    if detail == "volume_pin_missing":
        logger.error(VOLUME_PIN_MISSING_HINT)


def acquire_write_owner_at_worker_startup() -> tuple[bool, str]:
    ok, detail = try_acquire_write_owner_lock()
    if ok:
        return True, detail
    _log_volume_pin_missing_hint(detail)
    logger.error(
        "owner_guard: worker startup blocked (%s) — background writers will not start",
        detail,
    )
    return False, detail


def acquire_or_refuse(context: str) -> bool:
    ok, detail = try_acquire_write_owner_lock()
    if ok:
        return True
    _log_volume_pin_missing_hint(detail)
    logger.error("owner_guard: %s BLOCKED (%s)", context, detail)
    return False


def reset_owner_guard_for_tests() -> None:
    global _terminal_owner_lost, _terminal_exit_scheduled, _atexit_registered, _skip_dev_active
    _terminal_owner_lost = False
    _terminal_exit_scheduled = False
    _skip_dev_active = False
    _release_write_owner_lock()
    _atexit_registered = False


# Backwards-compatible helpers for tests migrating off v1 markers
def data_dir_fingerprint() -> str:
    root = resolved_data_dir()
    st = os.stat(root)
    return f"{st.st_dev}:{st.st_ino}"
