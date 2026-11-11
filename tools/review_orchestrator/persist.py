"""v0 tick persistence: per-tick files, atomic rename, create-if-absent."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TICKS_DIR = "ticks"
_ACTIVE_DIR = "active"
_ACTIVE_NAME = "in-flight.json"
_TICK_PREFIX = "tick-"
_TICK_SUFFIX = ".json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _tick_id_from_filename(name: str) -> str | None:
    if not name.startswith(_TICK_PREFIX) or not name.endswith(_TICK_SUFFIX):
        return None
    if name.endswith(".json.tmp") or ".tmp" in name:
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


def _write_tick_atomically(final_path: Path, payload: dict[str, Any]) -> None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = final_path.with_suffix(final_path.suffix + f".{secrets.token_hex(8)}.tmp")
    body = json.dumps(payload, sort_keys=True) + "\n"
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, final_path)


def _release_in_flight(state_dir: Path, tick_id: str) -> None:
    active = _active_path(state_dir)
    if not active.is_file():
        return
    try:
        data = json.loads(active.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if data.get("tick_id") == tick_id:
        try:
            active.unlink()
        except OSError:
            pass


def _validate_tick_file(path: Path, data: Any) -> tuple[dict[str, Any] | None, str | None]:
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
    return data, None


def _allocate_seq(state_dir: Path) -> int:
    """Durable monotonic seq from completed tick files in this store."""
    max_seq = 0
    ticks = _ticks_dir(state_dir)
    if ticks.is_dir():
        for path in ticks.iterdir():
            if _tick_id_from_filename(path.name) is None:
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            record, err = _validate_tick_file(path, raw)
            if err is not None or record is None:
                continue
            max_seq = max(max_seq, int(record["seq"]))
    return max_seq + 1


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

    in_flight_payload = {"tick_id": tick_id, "started_at": started_at}
    active = _active_path(state_dir)
    created = create_if_absent(active, in_flight_payload)
    overlap_with: str | None = None
    if not created:
        try:
            holder = json.loads(active.read_text(encoding="utf-8"))
            overlap_with = str(holder.get("tick_id", "unknown"))
        except (OSError, json.JSONDecodeError):
            overlap_with = "unknown"

    tick_payload: dict[str, Any] = {
        "tick_id": tick_id,
        "seq": seq,
        "status": "completed",
        "noop": noop,
        "overlap": overlap_with is not None,
        "overlap_with": overlap_with,
        "started_at": started_at,
        "completed_at": _utc_now_iso(),
    }
    final = _ticks_dir(state_dir) / f"tick-{tick_id}.json"
    try:
        _write_tick_atomically(final, tick_payload)
    finally:
        _release_in_flight(state_dir, tick_id)

    return TickResult(
        tick_id=tick_id,
        path=final,
        overlap=overlap_with is not None,
        overlap_with=overlap_with,
        noop=noop,
        seq=seq,
    )


def read_newest_completed_tick_report(state_dir: Path) -> NewestTickRead:
    """Return newest valid completed tick; invalid files are skipped with reasons."""
    state_dir = Path(state_dir)
    skipped: list[str] = []
    best: dict[str, Any] | None = None
    best_key: tuple[datetime, int] | None = None
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
        record, err = _validate_tick_file(path, raw)
        if err is not None or record is None:
            skipped.append(err or f"{path.name}:invalid")
            continue
        completed_at = _parse_utc_iso(record["completed_at"])
        assert completed_at is not None
        key = (completed_at, int(record["seq"]))
        if best_key is None or key > best_key:
            best_key = key
            best = record

    return NewestTickRead(tick=best, skipped=tuple(skipped))


def read_newest_completed_tick(state_dir: Path) -> dict[str, Any] | None:
    return read_newest_completed_tick_report(state_dir).tick
