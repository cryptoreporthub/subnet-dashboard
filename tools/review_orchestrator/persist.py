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
    object_type = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = 'ticks' COLLATE NOCASE"
    ).fetchone()
    if object_type is None or str(object_type[0]).casefold() != "table":
        return False

    if conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type = 'trigger' AND tbl_name = 'ticks' COLLATE NOCASE LIMIT 1"
    ).fetchone():
        return False

    table = next(
        (
            row
            for row in conn.execute("PRAGMA table_list").fetchall()
            if str(row[1]).casefold() == "ticks"
        ),
        None,
    )
    if table is None or table[2] != "table" or bool(table[4]):
        return False

    columns = conn.execute("PRAGMA table_info(ticks)").fetchall()
    primary_key = [row for row in columns if row[5]]
    if (
        len(primary_key) != 1
        or str(primary_key[0][1]).casefold() != "seq"
        or str(primary_key[0][2]).strip().upper() != "INTEGER"
    ):
        return False

    indexes = conn.execute("PRAGMA index_list('ticks')").fetchall()
    return not any(row[3] == "pk" for row in indexes)


def _ticks_has_a_trigger(conn: sqlite3.Connection) -> bool:
    """A trigger on `ticks` can RAISE(ROLLBACK), which destroys a savepoint.

    `tbl_name` is matched case-insensitively so a trigger on `TICKS` is caught.
    """
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'trigger' AND tbl_name = 'ticks' COLLATE NOCASE LIMIT 1"
        ).fetchone()
        is not None
    )


def _latest_object_is_usable(conn: sqlite3.Connection) -> bool:
    latest = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = 'latest' COLLATE NOCASE"
    ).fetchone()
    return latest is None or str(latest[0]).casefold() == "view"


_PROBE_TICK_ID = "__repair_probe__"


def _probe_store_behaviour(conn: sqlite3.Connection) -> bool:
    """Exercise the store the way the writer will, inside a rolled-back savepoint.

    Structural inspection cannot tell a benign CHECK from one that rejects every
    row, nor spot a column the writer never fills. Behaviour can. Everything here
    is undone by `ROLLBACK TO`, so a healthy store is left byte-identical.

    Returns False for any behaviour the writer depends on that the store lacks.
    Raises sqlite3.DatabaseError when the store rejects the probe outright.
    """
    conn.execute("SAVEPOINT repair_probe")
    try:
        started_at = utc_now().isoformat()

        # Insert like `start_tick`: only tick_id, started_at, overlap.
        cursor = conn.execute(
            "INSERT INTO ticks (tick_id, started_at, overlap) VALUES (?, ?, 0)",
            (_PROBE_TICK_ID, started_at),
        )
        rowid = cursor.lastrowid
        if not isinstance(rowid, int):
            return False

        # seq must alias the rowid, or MAX(seq) and the reader disagree.
        probe = conn.execute(
            "SELECT _rowid_, seq FROM ticks WHERE tick_id = ?", (_PROBE_TICK_ID,)
        ).fetchone()
        if probe is None or int(probe[0]) != int(probe[1]):
            return False
        seq = int(probe[1])

        # Complete like `complete_tick`.
        updated = conn.execute(
            "UPDATE ticks SET outcome = 'completed', duration_ms = 0, noop = 0 "
            "WHERE seq = ? AND duration_ms IS NULL",
            (seq,),
        )
        if updated.rowcount != 1:
            return False

        # The reader's view, if present, must see the probe row as the latest.
        # An absent view is fine: `connect` creates it. A table named `latest`
        # is an impostor and was already rejected structurally.
        if _latest_object_is_usable(conn) and conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'view' AND name = 'latest'"
        ).fetchone():
            latest = conn.execute("SELECT seq FROM latest").fetchone()
            if latest is None or int(latest[0]) != seq:
                return False

        # A duplicate tick_id must be rejected.
        try:
            conn.execute(
                "INSERT INTO ticks (tick_id, started_at, overlap) VALUES (?, ?, 0)",
                (_PROBE_TICK_ID, started_at),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            return False

        # AUTOINCREMENT must not reuse the seq of a deleted row.
        conn.execute("DELETE FROM ticks WHERE tick_id = ?", (_PROBE_TICK_ID,))
        cursor = conn.execute(
            "INSERT INTO ticks (tick_id, started_at, overlap) VALUES (?, ?, 0)",
            (f"{_PROBE_TICK_ID}_reuse", started_at),
        )
        reused = cursor.lastrowid
        if not isinstance(reused, int) or reused <= seq:
            return False

        # The counter must stay trustworthy: one row, integer, not poisoned.
        rows = conn.execute(
            "SELECT seq, typeof(seq) FROM sqlite_sequence "
            "WHERE name = 'ticks' COLLATE NOCASE"
        ).fetchall()
        if len(rows) != 1:
            return False
        sequence, value_type = rows[0]
        if value_type != "integer" or int(sequence) > db.MAX_TRUSTED_SEQ:
            return False
        if int(sequence) < reused:
            return False

        return True
    finally:
        # A trigger that already tore the savepoint down makes these no-ops;
        # never let cleanup mask the probe's own verdict or error.
        try:
            conn.execute("ROLLBACK TO SAVEPOINT repair_probe")
            conn.execute("RELEASE SAVEPOINT repair_probe")
        except sqlite3.OperationalError:
            pass


def _available_repair_target(path: Path, stamp: str) -> Path:
    target = path.with_name(f"{path.name}.corrupt-{stamp}")
    while any(
        Path(f"{target}{suffix}").exists() for suffix in ("", "-wal", "-shm")
    ):
        target = path.with_name(
            f"{path.name}.corrupt-{stamp}-{secrets.token_hex(6)}"
        )
    return target


def repair_store(state_dir: Path, *, stamp: str | None = None) -> Path:
    """Move an unreadable or untrusted store aside and return its new path.

    A healthy store is left in place. Its WAL sidecars move with the database.
    """
    state_dir = Path(state_dir)
    path = db.db_path(state_dir)
    if not state_dir.exists():
        return path
    stamp = stamp or utc_now().strftime("%Y%m%dT%H%M%SZ")
    try:
        with db.store_lock(state_dir, exclusive=True, recover_intent=False):
            recovered = db._recover_or_quarantine_repair_intent_locked(state_dir)
            if recovered is not None:
                return recovered
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
                    columns = {str(row[1]).casefold() for row in table_columns}
                    required_columns = {
                        name.strip().casefold() for name in db.COLUMNS.split(",")
                    }
                    structurally_trusted = (
                        check is not None
                        and str(check[0]).lower() == "ok"
                        and required_columns.issubset(columns)
                        and _seq_is_rowid_alias(conn)
                        and not _ticks_has_a_trigger(conn)
                        and _latest_object_is_usable(conn)
                    )
                    if not structurally_trusted:
                        corrupt = True
                    else:
                        maximum = conn.execute(
                            "SELECT MAX(seq) FROM ticks"
                        ).fetchone()[0]
                        corrupt = (
                            maximum is not None
                            and int(maximum) > db.MAX_TRUSTED_SEQ
                        ) or not _probe_store_behaviour(conn)
                except sqlite3.IntegrityError:
                    # The probe wrote a row the writer itself would write and the
                    # store refused it: the schema is hostile, not the access.
                    corrupt = True
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
                return db.move_store_aside(
                    path,
                    _available_repair_target(path, stamp),
                )
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

    state_dir = args.state_dir.resolve()
    quarantined_before = _orphaned_intents(state_dir)
    moved = repair_store(state_dir)
    quarantined = _orphaned_intents(state_dir) - quarantined_before

    if moved != db.db_path(state_dir):
        print(f"repair: moved corrupt store to {moved.name}")
    elif moved.exists():
        print("repair: healthy store; nothing moved")
    else:
        print("repair: no store to move")
    # An ambiguous or corrupt intent is quarantined, not repaired. Say so, or a
    # bare "no store to move" reads as "there was nothing wrong here".
    for orphan in sorted(quarantined):
        print(f"repair: quarantined unusable repair intent as {orphan.name}")
    return 0


def _orphaned_intents(state_dir: Path) -> set[Path]:
    return set(state_dir.glob(f"{db.REPAIR_INTENT_FILENAME}.orphan-*"))


if __name__ == "__main__":
    sys.exit(main())
