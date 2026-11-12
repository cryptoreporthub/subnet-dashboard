"""Tick persistence: a SQLite store with one writer and one reader view.

The public surface is small: run one tick, read the latest row, repair a store
that is not a database. Rate of change lives in `db`; the round-3 blockers from
the v1a review are closed there (age-bounded sweep, a terminal failure write,
and a schema invariant tying `duration_ms` to `outcome`).
"""

from __future__ import annotations

import argparse
import secrets
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from tools.review_orchestrator import db
from tools.review_orchestrator.db import (
    DuplicateTickIdError,
    StoreCorruptError,
    StoreUnavailableError,
)

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

    with db.locked_connect(state_dir) as conn:
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

    return TickResult(
        tick_id=tick_id,
        seq=opened.seq,
        outcome="completed",
        overlap=opened.overlap,
        noop=noop,
    )


def read_latest_tick(state_dir: Path) -> dict[str, Any] | None:
    with db.locked_connect(state_dir) as conn:
        row = db.latest_row(conn)
    return dict(row) if row is not None else None


def _seq_is_rowid_alias(conn: sqlite3.Connection) -> bool:
    probe_id = f"__repair_probe_{secrets.token_hex(8)}"
    conn.execute("SAVEPOINT repair_seq_probe")
    try:
        conn.execute(
            "INSERT INTO ticks "
            "(tick_id, started_at, duration_ms, outcome, noop, overlap, last_alert_ok) "
            "VALUES (?, ?, 0, 'completed', 0, 0, NULL)",
            (probe_id, utc_now().isoformat()),
        )
        row = conn.execute(
            "SELECT seq, rowid FROM ticks WHERE tick_id = ?", (probe_id,)
        ).fetchone()
        return row is not None and row[0] is not None and row[0] == row[1]
    except sqlite3.DatabaseError:
        return False
    finally:
        conn.execute("ROLLBACK TO repair_seq_probe")
        conn.execute("RELEASE repair_seq_probe")


def repair_store(state_dir: Path, *, stamp: str | None = None) -> Path:
    """Move an unreadable or untrusted store aside and return its new path.

    A healthy store is left in place. Its WAL sidecars move with the database.
    """
    state_dir = Path(state_dir)
    path = db.db_path(state_dir)
    if not state_dir.exists():
        return path
    stamp = stamp or utc_now().strftime("%Y%m%dT%H%M%SZ")
    moved = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        with db.store_lock(state_dir, exclusive=True):
            if not path.exists():
                return path

            conn = None
            try:
                corrupt = False
                try:
                    conn = sqlite3.connect(
                        str(path),
                        isolation_level=None,
                        timeout=db.BUSY_TIMEOUT_MS / 1000,
                    )
                    conn.execute(f"PRAGMA busy_timeout = {db.BUSY_TIMEOUT_MS}")
                    conn.execute("BEGIN IMMEDIATE")
                    check = conn.execute("PRAGMA quick_check").fetchone()
                    table_columns = conn.execute(
                        "PRAGMA table_info(ticks)"
                    ).fetchall()
                    columns = {row[1] for row in table_columns}
                    sequence_column = next(
                        (row for row in table_columns if row[1] == "seq"),
                        None,
                    )
                    required_columns = {
                        name.strip() for name in db.COLUMNS.split(",")
                    }
                    seq_is_rowid_alias = (
                        sequence_column is not None
                        and str(sequence_column[2]).strip().upper() == "INTEGER"
                        and sequence_column[5] == 1
                        and _seq_is_rowid_alias(conn)
                    )
                    if (
                        check is None
                        or str(check[0]).lower() != "ok"
                        or not required_columns.issubset(columns)
                        or not seq_is_rowid_alias
                    ):
                        corrupt = True
                    else:
                        maximum = conn.execute(
                            "SELECT MAX(seq) FROM ticks"
                        ).fetchone()[0]
                        corrupt = (
                            maximum is not None
                            and int(maximum) > db.MAX_TRUSTED_SEQ
                        )
                except sqlite3.DatabaseError as exc:
                    if isinstance(exc, sqlite3.OperationalError) and db._is_busy_or_locked(
                        exc
                    ):
                        raise
                    classified = db._store_error(exc, path)
                    if isinstance(classified, StoreCorruptError):
                        corrupt = True
                    else:
                        raise classified from exc

                if not corrupt:
                    if conn is not None and conn.in_transaction:
                        conn.execute("ROLLBACK")
                    return path
                if conn is not None:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    conn.close()
                    conn = None
                return db.move_store_aside(path, moved)
            finally:
                if conn is not None:
                    conn.close()
    except OSError as exc:
        raise StoreUnavailableError(f"{path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Review orchestrator store maintenance"
    )
    parser.add_argument("command", choices=["repair"])
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    moved = repair_store(args.state_dir.resolve())
    if moved != db.db_path(args.state_dir.resolve()):
        print(f"repair: moved corrupt store to {moved.name}")
    elif moved.exists():
        print("repair: healthy store; nothing moved")
    else:
        print("repair: no store to move")
    return 0


if __name__ == "__main__":
    sys.exit(main())
