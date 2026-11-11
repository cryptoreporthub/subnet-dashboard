"""Tick persistence: a SQLite store with one writer and one reader view.

The public surface is small: run one tick, read the latest row, repair a store
that is not a database. Rate of change lives in `db`; the round-3 blockers from
the v1a review are closed there (age-bounded sweep, a terminal failure write,
and a schema invariant tying `duration_ms` to `outcome`).
"""

from __future__ import annotations

import argparse
import secrets
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from tools.review_orchestrator import db
from tools.review_orchestrator.db import DuplicateTickIdError, StoreUnavailableError

#: A running row older than this is swept to 'abandoned' before the next tick
#: measures overlap, so a tick SIGKILLed between start and completion cannot pin
#: `overlap` on for the life of the store.
ABANDONED_AFTER = timedelta(minutes=40)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc_iso(value: Any) -> datetime | None:
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


# Private aliases kept for callers in this repo (exams and tests).
_utc_now = utc_now
_parse_utc_iso = parse_utc_iso


@dataclass(frozen=True)
class TickResult:
    tick_id: str
    seq: int
    outcome: str
    overlap: bool
    noop: bool


def _elapsed_ms(started_monotonic: float) -> int:
    return max(0, int((time.monotonic() - started_monotonic) * 1000))


def run_tick(
    state_dir: Path,
    *,
    tick_id: str | None = None,
    noop: bool = False,
    work: Callable[[], None] | None = None,
) -> TickResult:
    """Open a running row, run `work` outside any transaction, then close the row.

    If `work` raises, the row is closed `failed` with a duration and the error is
    re-raised. A SIGKILL leaves the row `running`; the next tick sweeps it and the
    dead-man reports it as `attempt_stale` past the age limit.
    """
    state_dir = Path(state_dir)
    tick_id = tick_id or secrets.token_hex(8)
    started = utc_now()
    started_at = started.isoformat()
    cutoff = (started - ABANDONED_AFTER).isoformat()

    conn = db.connect(state_dir)
    try:
        opened = db.start_tick(conn, tick_id, started_at, cutoff_iso=cutoff)
        started_monotonic = time.monotonic()
        try:
            if work is not None:
                work()
        except BaseException:
            db.complete_tick(
                conn,
                opened.seq,
                outcome="failed",
                duration_ms=_elapsed_ms(started_monotonic),
                noop=noop,
            )
            raise
        db.complete_tick(
            conn,
            opened.seq,
            outcome="completed",
            duration_ms=_elapsed_ms(started_monotonic),
            noop=noop,
        )
    finally:
        conn.close()

    return TickResult(
        tick_id=tick_id,
        seq=opened.seq,
        outcome="completed",
        overlap=opened.overlap,
        noop=noop,
    )


def read_latest_tick(state_dir: Path) -> dict[str, Any] | None:
    conn = db.connect(state_dir)
    try:
        row = db.latest_row(conn)
    finally:
        conn.close()
    return dict(row) if row is not None else None


def repair_store(state_dir: Path, *, stamp: str | None = None) -> Path:
    """Move a store that is not a database aside and return its new path.

    Returns the store path unchanged when there is nothing to repair.
    """
    path = db.db_path(Path(state_dir))
    if not path.exists():
        return path
    stamp = stamp or utc_now().strftime("%Y%m%dT%H%M%SZ")
    moved = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        path.replace(moved)
    except PermissionError as exc:
        # A read-only directory is not a corrupt store: `repair` itself cannot
        # run. Name the real problem instead of letting a traceback escape.
        raise StoreUnavailableError(f"{path}: {exc}") from exc
    return moved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Review orchestrator store maintenance"
    )
    parser.add_argument("command", choices=["repair"])
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    moved = repair_store(args.state_dir.resolve())
    if moved == db.db_path(args.state_dir.resolve()):
        print("repair: no store to move")
    else:
        print(f"repair: moved corrupt store to {moved.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
