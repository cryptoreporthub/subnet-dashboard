"""v0 tick persistence: per-tick files, atomic rename, create-if-absent."""

from __future__ import annotations

import fcntl
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_TICKS_DIR = "ticks"
_ACTIVE_DIR = "active"
_ACTIVE_NAME = "in-flight.json"
_SEQ_DIR = "seq"
_HEARTBEAT_DIR = "heartbeat"
_HEARTBEAT_NAME = "latest.json"
_HEARTBEAT_LOCK_NAME = ".publish.lock"
_RESERVE_SUFFIX = ".reserve.json"
_TICK_PREFIX = "tick-"
_TICK_SUFFIX = ".json"
_COMPLETION_FUTURE_SLACK = timedelta(minutes=5)

# ponytail: kill -9 mid-tick can leave active/in-flight.json; staleness eviction is v1.


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _ticks_dir(state_dir: Path) -> Path:
    return state_dir / _TICKS_DIR


def _active_path(state_dir: Path) -> Path:
    return state_dir / _ACTIVE_DIR / _ACTIVE_NAME


def _seq_dir(state_dir: Path) -> Path:
    return state_dir / _SEQ_DIR


def _heartbeat_path(state_dir: Path) -> Path:
    return state_dir / _HEARTBEAT_DIR / _HEARTBEAT_NAME


def _tick_id_from_filename(name: str) -> str | None:
    if not name.startswith(_TICK_PREFIX) or not name.endswith(_TICK_SUFFIX):
        return None
    if name.endswith(_RESERVE_SUFFIX) or name.endswith(".json.tmp") or ".tmp" in name:
        return None
    return name[len(_TICK_PREFIX) : -len(_TICK_SUFFIX)]


def create_if_absent(path: Path, payload: dict[str, Any]) -> bool:
    """Write JSON at path only when missing. Returns True if this call created it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, sort_keys=True) + "\n"
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(8)}.tmp")
    tmp_fd: int | None = None
    try:
        tmp_fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            tmp_fd = None
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(str(tmp), str(path))
        except FileExistsError:
            return False
        os.unlink(tmp)
        return True
    finally:
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _heartbeat_order_key(record: dict[str, Any]) -> tuple[datetime, datetime, str] | None:
    attempt = _parse_utc_iso(record.get("attempt_at"))
    completed = _parse_utc_iso(record.get("completed_at"))
    tick_id = record.get("tick_id")
    if attempt is None or completed is None or not isinstance(tick_id, str) or not tick_id:
        return None
    return (attempt, completed, tick_id)


def _heartbeat_beats(incumbent: dict[str, Any] | None, candidate: dict[str, Any]) -> bool:
    """True when candidate should replace incumbent (strictly newer)."""
    candidate_key = _heartbeat_order_key(candidate)
    if candidate_key is None:
        return False
    if incumbent is None:
        return True
    incumbent_key = _heartbeat_order_key(incumbent)
    if incumbent_key is None:
        return True
    return candidate_key > incumbent_key


def _read_heartbeat_dict(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def _publish_heartbeat_monotonic(state_dir: Path, payload: dict[str, Any]) -> None:
    """Replace heartbeat/latest.json only when payload is newer than the current file."""
    hb_dir = state_dir / _HEARTBEAT_DIR
    hb_dir.mkdir(parents=True, exist_ok=True)
    lock_path = hb_dir / _HEARTBEAT_LOCK_NAME
    hb_path = _heartbeat_path(state_dir)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        incumbent = _read_heartbeat_dict(hb_path)
        if not _heartbeat_beats(incumbent, payload):
            return
        _write_tick_atomically(hb_path, payload)


def _write_tick_atomically(final_path: Path, payload: dict[str, Any]) -> None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = final_path.with_suffix(final_path.suffix + f".{secrets.token_hex(8)}.tmp")
    body = json.dumps(payload, sort_keys=True) + "\n"
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, final_path)


def _release_in_flight(state_dir: Path, owner_token: str) -> None:
    active = _active_path(state_dir)
    if not active.is_file():
        return
    try:
        data = json.loads(active.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if data.get("owner_token") == owner_token:
        try:
            active.unlink()
        except OSError:
            pass


def _validate_tick_file(
    path: Path,
    data: Any,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(data, dict):
        return None, f"{path.name}:not_a_dict"
    filename_id = _tick_id_from_filename(path.name)
    if filename_id is None:
        return None, f"{path.name}:bad_filename"
    tick_id = data.get("tick_id")
    if not isinstance(tick_id, str) or tick_id != filename_id:
        return None, f"{path.name}:tick_id_mismatch"
    if data.get("status") != "completed":
        return None, f"{path.name}:not_completed"
    seq = data.get("seq")
    if not isinstance(seq, int):
        return None, f"{path.name}:bad_seq"
    started_at = _parse_utc_iso(data.get("started_at"))
    completed_at = _parse_utc_iso(data.get("completed_at"))
    if started_at is None:
        return None, f"{path.name}:bad_started_at"
    if completed_at is None:
        return None, f"{path.name}:bad_completed_at"
    if started_at > completed_at:
        return None, f"{path.name}:start_after_end"
    reference = now if now is not None else _utc_now()
    if completed_at > reference + _COMPLETION_FUTURE_SLACK:
        return None, f"{path.name}:completed_at_in_future"
    return data, None


def _highest_claimed_seq(state_dir: Path) -> int:
    seq_root = _seq_dir(state_dir)
    if not seq_root.is_dir():
        return 0
    best = 0
    for path in seq_root.iterdir():
        if not path.is_file() or not path.name.endswith(".json"):
            continue
        try:
            value = int(path.stem)
        except ValueError:
            continue
        best = max(best, value)
    return best


def _allocate_seq(state_dir: Path) -> int:
    """Claim the next seq with create-if-absent on seq/<n>.json; retry on collision."""
    for _ in range(10_000):
        candidate = _highest_claimed_seq(state_dir) + 1
        claim = _seq_dir(state_dir) / f"{candidate}.json"
        if create_if_absent(claim, {"seq": candidate, "claimed_at": _utc_now_iso()}):
            return candidate
    raise RuntimeError("seq claim retries exhausted")


@dataclass(frozen=True)
class TickResult:
    tick_id: str
    path: Path
    overlap: bool
    overlap_with: str | None
    noop: bool
    seq: int


@dataclass(frozen=True)
class NewestTickRead:
    tick: dict[str, Any] | None
    skipped: tuple[str, ...]


class DuplicateTickIdError(ValueError):
    """Caller-supplied tick_id is already reserved or completed in this store."""


def _tick_path(state_dir: Path, tick_id: str) -> Path:
    return _ticks_dir(state_dir) / f"{_TICK_PREFIX}{tick_id}{_TICK_SUFFIX}"


def _tick_reserve_path(state_dir: Path, tick_id: str) -> Path:
    return _ticks_dir(state_dir) / f"{_TICK_PREFIX}{tick_id}{_RESERVE_SUFFIX}"


def _release_tick_reserve(state_dir: Path, owner_token: str) -> None:
    reserve_dir = _ticks_dir(state_dir)
    if not reserve_dir.is_dir():
        return
    for path in reserve_dir.glob(f"{_TICK_PREFIX}*{_RESERVE_SUFFIX}"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("owner_token") == owner_token:
            try:
                path.unlink()
            except OSError:
                pass


def run_tick(
    state_dir: Path,
    *,
    tick_id: str | None = None,
    noop: bool = False,
) -> TickResult:
    """Run one orchestrator tick: claim in-flight slot, persist completed tick file."""
    state_dir = Path(state_dir)
    tick_id = tick_id or secrets.token_hex(8)
    started_at = _utc_now_iso()
    seq = _allocate_seq(state_dir)
    owner_token = secrets.token_hex(8)

    reserve = _tick_reserve_path(state_dir, tick_id)
    if not create_if_absent(
        reserve,
        {"tick_id": tick_id, "owner_token": owner_token, "started_at": started_at},
    ):
        raise DuplicateTickIdError(tick_id)

    final = _tick_path(state_dir, tick_id)
    if final.is_file():
        _release_tick_reserve(state_dir, owner_token)
        raise DuplicateTickIdError(tick_id)

    in_flight_payload = {
        "tick_id": tick_id,
        "started_at": started_at,
        "owner_token": owner_token,
    }
    active = _active_path(state_dir)
    created = create_if_absent(active, in_flight_payload)
    overlap_with: str | None = None
    if not created:
        try:
            holder = json.loads(active.read_text(encoding="utf-8"))
            overlap_with = str(holder.get("tick_id", "unknown"))
        except (OSError, json.JSONDecodeError):
            overlap_with = "unknown"

    overlap = overlap_with is not None
    tick_payload: dict[str, Any] = {
        "tick_id": tick_id,
        "seq": seq,
        "status": "completed",
        "noop": noop,
        "overlap": overlap,
        "started_at": started_at,
        "completed_at": _utc_now_iso(),
    }
    if overlap_with is not None:
        tick_payload["overlap_with"] = overlap_with
    completed_at = tick_payload["completed_at"]
    try:
        _write_tick_atomically(final, tick_payload)
        _publish_heartbeat_monotonic(
            state_dir,
            {
                "tick_id": tick_id,
                "attempt_at": started_at,
                "completed_at": completed_at,
            },
        )
    finally:
        _release_in_flight(state_dir, owner_token)
        _release_tick_reserve(state_dir, owner_token)

    return TickResult(
        tick_id=tick_id,
        path=final,
        overlap=overlap,
        overlap_with=overlap_with,
        noop=noop,
        seq=seq,
    )


def read_newest_completed_tick_report(
    state_dir: Path,
    *,
    now: datetime | None = None,
) -> NewestTickRead:
    """Return newest valid completed tick; invalid files are skipped with reasons."""
    state_dir = Path(state_dir)
    reference = now if now is not None else _utc_now()
    skipped: list[str] = []
    best: dict[str, Any] | None = None
    best_key: tuple[int, datetime] | None = None
    ticks = _ticks_dir(state_dir)
    if not ticks.is_dir():
        return NewestTickRead(tick=None, skipped=tuple(skipped))

    for path in sorted(ticks.iterdir()):
        if not path.is_file():
            continue
        if _tick_id_from_filename(path.name) is None:
            skipped.append(f"{path.name}:bad_filename")
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            skipped.append(f"{path.name}:json_error")
            continue
        record, err = _validate_tick_file(path, raw, now=reference)
        if err is not None or record is None:
            skipped.append(err or f"{path.name}:invalid")
            continue
        completed_at = _parse_utc_iso(record["completed_at"])
        assert completed_at is not None
        key = (int(record["seq"]), completed_at)
        if best_key is None or key > best_key:
            best_key = key
            best = record

    return NewestTickRead(tick=best, skipped=tuple(skipped))


def read_newest_completed_tick(state_dir: Path) -> dict[str, Any] | None:
    return read_newest_completed_tick_report(state_dir).tick
