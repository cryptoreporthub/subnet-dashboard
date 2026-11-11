"""v0 tick persistence: per-tick files, atomic rename, create-if-absent."""

from __future__ import annotations

import json
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TICKS_DIR = "ticks"
_ACTIVE_DIR = "active"
_ACTIVE_NAME = "in-flight.json"
_SEQ_LOCK = threading.Lock()
_SEQ = 0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_seq() -> int:
    global _SEQ
    with _SEQ_LOCK:
        _SEQ += 1
        return _SEQ


def _ticks_dir(state_dir: Path) -> Path:
    return state_dir / _TICKS_DIR


def _active_path(state_dir: Path) -> Path:
    return state_dir / _ACTIVE_DIR / _ACTIVE_NAME


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


@dataclass(frozen=True)
class TickResult:
    tick_id: str
    path: Path
    overlap: bool
    overlap_with: str | None
    noop: bool
    seq: int


def run_tick(
    state_dir: Path,
    *,
    tick_id: str | None = None,
    noop: bool = False,
) -> TickResult:
    """Run one orchestrator tick: claim in-flight slot, persist completed tick file."""
    state_dir = Path(state_dir)
    tick_id = tick_id or secrets.token_hex(8)
    seq = _next_seq()

    in_flight_payload = {"tick_id": tick_id, "started_at": _utc_now_iso()}
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
        "completed_at": _utc_now_iso(),
    }
    final = _ticks_dir(state_dir) / f"tick-{tick_id}.json"
    _write_tick_atomically(final, tick_payload)
    _release_in_flight(state_dir, tick_id)

    return TickResult(
        tick_id=tick_id,
        path=final,
        overlap=overlap_with is not None,
        overlap_with=overlap_with,
        noop=noop,
        seq=seq,
    )


def _iter_completed_tick_paths(state_dir: Path) -> list[Path]:
    ticks = _ticks_dir(state_dir)
    if not ticks.is_dir():
        return []
    paths: list[Path] = []
    for entry in ticks.iterdir():
        name = entry.name
        if not name.endswith(".json"):
            continue
        if name.endswith(".json.tmp") or ".tmp" in name:
            continue
        paths.append(entry)
    return paths


def read_newest_completed_tick(state_dir: Path) -> dict[str, Any] | None:
    """Return the newest completed tick record, ignoring incomplete .tmp files."""
    state_dir = Path(state_dir)
    best: dict[str, Any] | None = None
    best_key: tuple[int, str] | None = None
    for path in _iter_completed_tick_paths(state_dir):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") != "completed":
            continue
        completed_at = str(data.get("completed_at", ""))
        seq = int(data.get("seq", 0))
        key = (seq, completed_at)
        if best_key is None or key > best_key:
            best_key = key
            best = data
    return best
