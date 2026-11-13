"""Tick persistence: a SQLite store with one writer and one reader view.

The public surface is small: run one tick, read the latest row, repair a store
that is not a database. Rate of change lives in `db`; the round-3 blockers from
the v1a review are closed there (age-bounded sweep, a terminal failure write,
and a schema invariant tying `duration_ms` to `outcome`).
"""

from __future__ import annotations

import argparse
import re
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


def _table_definitions(sql: str) -> list[str]:
    """Return CREATE TABLE definitions split only at top-level commas."""
    definitions: list[str] = []
    depth = 0
    start = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            index = len(sql) if newline < 0 else newline + 1
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            index = len(sql) if end < 0 else end + 2
            continue
        if char in ("'", '"', "`", "["):
            closing = "]" if char == "[" else char
            index += 1
            while index < len(sql):
                if sql[index] == closing:
                    if closing != "]" and index + 1 < len(sql) and sql[index + 1] == closing:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == "(":
            if depth == 0:
                start = index + 1
            depth += 1
        elif char == ")" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                definitions.append(sql[start:index].strip())
                return definitions
        elif char == "," and depth == 1 and start is not None:
            definitions.append(sql[start:index].strip())
            start = index + 1
        index += 1
    return []


def _leading_identifier(definition: str) -> str | None:
    match = re.match(
        r'\s*(?:"((?:""|[^"])*)"|`([^`]*)`|\[([^\]]*)\]|([^\s,()]+))',
        definition,
    )
    if match is None:
        return None
    for group in match.groups()[:3]:
        if group is not None:
            return group.replace('""', '"')
    return match.group(4)


def _top_level_keywords(sql: str) -> list[str]:
    words: list[str] = []
    depth = 0
    index = 0
    while index < len(sql):
        char = sql[index]
        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            index = len(sql) if newline < 0 else newline + 1
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            index = len(sql) if end < 0 else end + 2
            continue
        if char in ("'", '"', "`", "["):
            closing = "]" if char == "[" else char
            index += 1
            while index < len(sql):
                if sql[index] == closing:
                    if closing != "]" and index + 1 < len(sql) and sql[index + 1] == closing:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            index += 1
            continue
        if depth == 0 and (char.isalpha() or char == "_"):
            end = index + 1
            while end < len(sql) and (
                sql[end].isalnum() or sql[end] in "_$"
            ):
                end += 1
            words.append(sql[index:end].upper())
            index = end
            continue
        index += 1
    return words


def _seq_uses_autoincrement(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type = 'table' AND name = 'ticks' COLLATE NOCASE"
    ).fetchone()
    if row is None or not isinstance(row[0], str):
        return False
    for definition in _table_definitions(row[0]):
        column_name = _leading_identifier(definition)
        if column_name is None or column_name.casefold() != "seq":
            continue
        words = _top_level_keywords(definition)
        for index in range(len(words) - 2):
            if words[index : index + 2] == ["PRIMARY", "KEY"]:
                return "AUTOINCREMENT" in words[index + 2 :]
    return False


def _tick_id_is_unique(conn: sqlite3.Connection) -> bool:
    for index in conn.execute("PRAGMA index_list('ticks')").fetchall():
        if not index[2] or (len(index) > 4 and index[4]):
            continue
        index_name = '"' + str(index[1]).replace('"', '""') + '"'
        columns = conn.execute(f"PRAGMA index_info({index_name})").fetchall()
        if (
            len(columns) == 1
            and columns[0][2] is not None
            and str(columns[0][2]).casefold() == "tick_id"
        ):
            return True
    return False


def _sqlite_sequence_is_healthy(conn: sqlite3.Connection) -> bool:
    sequence_table = conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type = 'table' AND name = 'sqlite_sequence' COLLATE NOCASE"
    ).fetchone()
    if sequence_table is None:
        return False
    rows = conn.execute(
        "SELECT seq, typeof(seq) FROM sqlite_sequence "
        "WHERE name = 'ticks' COLLATE NOCASE"
    ).fetchall()
    if len(rows) > 1:
        return False
    maximum = conn.execute("SELECT MAX(seq) FROM ticks").fetchone()[0]
    if not rows:
        return maximum is None
    sequence, value_type = rows[0]
    return (
        value_type == "integer"
        and 0 <= sequence <= db.MAX_TRUSTED_SEQ
        and (maximum is None or sequence >= maximum)
    )


def _latest_object_is_usable(conn: sqlite3.Connection) -> bool:
    latest = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = 'latest' COLLATE NOCASE"
    ).fetchone()
    return latest is None or str(latest[0]).casefold() == "view"


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
                    seq_is_rowid_alias = _seq_is_rowid_alias(conn)
                    if (
                        check is None
                        or str(check[0]).lower() != "ok"
                        or not required_columns.issubset(columns)
                        or not seq_is_rowid_alias
                        or not _seq_uses_autoincrement(conn)
                        or not _tick_id_is_unique(conn)
                        or not _sqlite_sequence_is_healthy(conn)
                        or not _latest_object_is_usable(conn)
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
