"""Cross-process persist gate: per-domain epoch file + flock (Design A)."""

from __future__ import annotations

import fcntl
import logging
import os
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable, Dict, Iterator, Optional

logger = logging.getLogger(__name__)


class TicketRefused(Exception):
    """Raised when commit rejects unknown or stale ticket."""


class EpochCorrupt(Exception):
    """Epoch file unreadable — refuse mint/commit until revoke repairs it."""


_domain_lock_holder: ContextVar[Optional[str]] = ContextVar(
    "domain_write_gate_lock_holder", default=None
)


def domain_lock_held(domain: str) -> bool:
    return _domain_lock_holder.get() == domain


@dataclass(frozen=True)
class WriteTicket:
    domain: str
    epoch: int
    run_id: str


_DOMAIN_DEFAULTS: Dict[str, Dict[str, str]] = {
    "predictions": {
        "lock_env": "PREDICTIONS_LOCK_PATH",
        "lock_default": os.path.join("data", "predictions.json.lock"),
        "epoch_env": "PREDICTIONS_EPOCH_PATH",
        "epoch_default": os.path.join("data", "predictions.epoch"),
    },
    "soul_map": {
        "lock_env": "SOUL_MAP_LOCK_PATH",
        "lock_default": os.path.join("data", "soul_map.json.lock"),
        "epoch_env": "SOUL_MAP_EPOCH_PATH",
        "epoch_default": os.path.join("data", "soul_map.epoch"),
    },
    "cycle_summary": {
        "lock_env": "SOUL_MAP_LOCK_PATH",
        "lock_default": os.path.join("data", "soul_map.json.lock"),
        "epoch_env": "CYCLE_SUMMARY_EPOCH_PATH",
        "epoch_default": os.path.join("data", "cycle_summary.epoch"),
    },
    "daily_pick": {
        "lock_env": "DAILY_PICKS_LOCK_PATH",
        "lock_default": os.path.join("data", "daily_picks.json.lock"),
        "epoch_env": "DAILY_PICK_EPOCH_PATH",
        "epoch_default": os.path.join("data", "daily_pick.epoch"),
    },
    "resolver": {
        "lock_env": "RESOLVER_GATE_LOCK_PATH",
        "lock_default": os.path.join("data", "resolver.epoch.lock"),
        "epoch_env": "RESOLVER_EPOCH_PATH",
        "epoch_default": os.path.join("data", "resolver.epoch"),
    },
}


def _cfg(domain: str) -> Dict[str, str]:
    if domain not in _DOMAIN_DEFAULTS:
        raise KeyError(f"unknown persist domain: {domain}")
    spec = _DOMAIN_DEFAULTS[domain]
    return {
        "lock_path": os.environ.get(spec["lock_env"], spec["lock_default"]),
        "epoch_path": os.environ.get(spec["epoch_env"], spec["epoch_default"]),
    }


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _read_epoch_unlocked(domain: str) -> int:
    path = _cfg(domain)["epoch_path"]
    _ensure_parent(path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read().strip()
        return max(0, int(raw or "0"))
    except FileNotFoundError:
        return 0
    except (TypeError, ValueError, OSError) as exc:
        logger.warning("domain_write_gate: corrupt epoch file domain=%s err=%s", domain, exc)
        raise EpochCorrupt(domain) from exc


def _write_epoch_unlocked(domain: str, epoch: int) -> None:
    path = _cfg(domain)["epoch_path"]
    _ensure_parent(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(str(int(epoch)))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def read_epoch(domain: str) -> int:
    with domain_lock(domain, timeout_seconds=2.0):
        return _read_epoch_unlocked(domain)


def _acquire_flock(lock_file, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            time.sleep(0.01)
        except OSError as exc:
            logger.warning("domain_write_gate flock error domain lock: %s", exc)
            raise
    raise TimeoutError(f"Timed out after {timeout_seconds}s waiting for domain lock")


@contextmanager
def domain_lock(domain: str, *, timeout_seconds: float = 5.0) -> Iterator[None]:
    lock_path = _cfg(domain)["lock_path"]
    _ensure_parent(lock_path)
    token = _domain_lock_holder.set(domain)
    try:
        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            _acquire_flock(lock_file, timeout_seconds=timeout_seconds)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        _domain_lock_holder.reset(token)


def mint_ticket(domain: str, run_id: Optional[str] = None) -> WriteTicket:
    """Capture current epoch under domain lock (web/worker before async work)."""
    rid = (run_id or "").strip() or uuid.uuid4().hex
    with domain_lock(domain, timeout_seconds=5.0):
        try:
            epoch = _read_epoch_unlocked(domain)
        except EpochCorrupt as exc:
            raise TicketRefused(f"corrupt epoch domain={domain}") from exc
    return WriteTicket(domain=domain, epoch=epoch, run_id=rid)


def mint_web_ticket(domain: str, *, purpose: str) -> WriteTicket:
    """Short-lived web ticket on the current epoch (fences stale runs, not appends)."""
    return mint_ticket(domain, run_id=f"web:{purpose}:{uuid.uuid4().hex[:12]}")


def revoke(domain: str, *, reason: str = "") -> int:
    """Bump epoch under domain lock — invalidates in-flight tickets."""
    with domain_lock(domain, timeout_seconds=5.0):
        try:
            epoch = _read_epoch_unlocked(domain) + 1
        except EpochCorrupt:
            epoch = 1
        _write_epoch_unlocked(domain, epoch)
    logger.info("domain_write_gate revoked domain=%s epoch=%s reason=%s", domain, epoch, reason or "unspecified")
    return epoch


def commit(
    ticket: WriteTicket,
    write_fn: Callable[[], None],
    *,
    lock_timeout: float = 5.0,
) -> bool:
    """Hold domain lock through epoch re-read, ticket check, and write_fn."""
    if not ticket or not ticket.domain or not ticket.run_id:
        return False
    try:
        with domain_lock(ticket.domain, timeout_seconds=lock_timeout):
            try:
                epoch = _read_epoch_unlocked(ticket.domain)
            except EpochCorrupt:
                logger.warning(
                    "domain_write_gate commit refused corrupt epoch domain=%s run_id=%s",
                    ticket.domain,
                    ticket.run_id,
                )
                return False
            if epoch != ticket.epoch:
                logger.info(
                    "domain_write_gate commit refused stale ticket domain=%s ticket_epoch=%s file_epoch=%s run_id=%s",
                    ticket.domain,
                    ticket.epoch,
                    epoch,
                    ticket.run_id,
                )
                return False
            write_fn()
        return True
    except TimeoutError:
        logger.warning(
            "domain_write_gate commit lock timeout domain=%s run_id=%s",
            ticket.domain,
            ticket.run_id,
        )
        return False


def commit_or_raise(ticket: WriteTicket, write_fn: Callable[[], None], *, lock_timeout: float = 5.0) -> None:
    if not commit(ticket, write_fn, lock_timeout=lock_timeout):
        raise TicketRefused(
            f"commit refused domain={ticket.domain} epoch={ticket.epoch} run_id={ticket.run_id}"
        )
