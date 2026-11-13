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
    dead-man reports it as `attempt_stale` past the age limit. If a sweeper
    abandons this row while work runs, the returned outcome is `abandoned`.
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
        completion_outcome = db.complete_tick(
            conn,
            opened.seq,
            outcome="completed",
            duration_ms=_elapsed_ms(started_monotonic),
            noop=noop,
        )

    return TickResult(
        tick_id=tick_id,
        seq=opened.seq,
        outcome=completion_outcome,
        overlap=opened.overlap,
        noop=noop,
    )


def read_latest_tick(state_dir: Path) -> dict[str, Any] | None:
    with db.locked_connect(state_dir) as conn:
        row = db.latest_row(conn)
    return dict(row) if row is not None else None


def _sql_tokens(sql: str) -> list[tuple[str, str]]:
    """Tokenize SQLite DDL, discarding comments but preserving quoted values."""
    tokens: list[tuple[str, str]] = []
    i = 0
    while i < len(sql):
        char = sql[i]
        if char.isspace():
            i += 1
            continue
        if sql.startswith("--", i):
            newline = sql.find("\n", i + 2)
            i = len(sql) if newline < 0 else newline + 1
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            if end < 0:
                return []
            i = end + 2
            continue
        if char in ("'", '"', "`", "["):
            closing = "]" if char == "[" else char
            i += 1
            value: list[str] = []
            while i < len(sql):
                if sql[i] == closing:
                    if closing != "]" and i + 1 < len(sql) and sql[i + 1] == closing:
                        value.append(closing)
                        i += 2
                        continue
                    i += 1
                    break
                value.append(sql[i])
                i += 1
            else:
                return []
            kind = "string" if char == "'" else "ident"
            token_value = "".join(value)
            if kind == "ident":
                token_value = token_value.casefold()
            tokens.append((kind, token_value))
            continue
        if char.isascii() and (char.isalpha() or char == "_"):
            end = i + 1
            while end < len(sql) and (
                sql[end].isascii()
                and (sql[end].isalnum() or sql[end] in "_$")
            ):
                end += 1
            value = sql[i:end]
            tokens.append(("ident", value.casefold()))
            i = end
            continue
        if char.isascii() and char.isdigit():
            end = i + 1
            while end < len(sql) and sql[end].isascii() and sql[end].isdigit():
                end += 1
            if (
                end + 1 < len(sql)
                and sql[end] == "."
                and sql[end + 1].isascii()
                and sql[end + 1].isdigit()
            ):
                end += 1
                while end < len(sql) and sql[end].isascii() and sql[end].isdigit():
                    end += 1
            value = sql[i:end]
            tokens.append(("number", value))
            i = end
            continue
        pair = sql[i : i + 2]
        if pair in {"<=", ">=", "!=", "<>", "||", "=="}:
            tokens.append(("symbol", pair))
            i += 2
        else:
            tokens.append(("symbol", char))
            i += 1
    return tokens


def _token_values(tokens: list[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    return tuple(tokens)


def _unwrap_sql_parens(tokens: list[tuple[str, str]]) -> list[tuple[str, str]]:
    while len(tokens) >= 2 and tokens[0] == ("symbol", "("):
        depth = 0
        closes_at_end = False
        for index, token in enumerate(tokens):
            if token == ("symbol", "("):
                depth += 1
            elif token == ("symbol", ")"):
                depth -= 1
                if depth == 0:
                    closes_at_end = index == len(tokens) - 1
                    break
        if not closes_at_end:
            break
        tokens = tokens[1:-1]
    return tokens


def _check_expressions(sql: str) -> list[tuple[tuple[str, str], ...]] | None:
    tokens = _sql_tokens(sql)
    if not tokens:
        return None
    opening = next(
        (index for index, token in enumerate(tokens) if token == ("symbol", "(")),
        None,
    )
    if opening is None:
        return None
    depth = 0
    closing = None
    for index in range(opening, len(tokens)):
        if tokens[index] == ("symbol", "("):
            depth += 1
        elif tokens[index] == ("symbol", ")"):
            depth -= 1
            if depth == 0:
                closing = index
                break
    if closing is None:
        return None

    checks: list[tuple[tuple[str, str], ...]] = []
    index = opening + 1
    while index < closing:
        if tokens[index] == ("ident", "check") and index + 1 < closing:
            if tokens[index + 1] != ("symbol", "("):
                return None
            depth = 1
            end = index + 2
            while end < closing and depth:
                if tokens[end] == ("symbol", "("):
                    depth += 1
                elif tokens[end] == ("symbol", ")"):
                    depth -= 1
                end += 1
            if depth:
                return None
            expression = _unwrap_sql_parens(tokens[index + 2 : end - 1])
            checks.append(_token_values(expression))
            index = end
        else:
            index += 1
    return checks


def _normalized_expression(expression: str) -> tuple[tuple[str, str], ...]:
    return _token_values(_unwrap_sql_parens(_sql_tokens(expression)))


_CANONICAL_CHECKS = {
    _normalized_expression("length(started_at) BETWEEN 20 AND 40"),
    _normalized_expression("duration_ms IS NULL OR duration_ms >= 0"),
    _normalized_expression(
        "outcome IN ('running', 'completed', 'failed', 'abandoned')"
    ),
    _normalized_expression("noop IN (0, 1)"),
    _normalized_expression("overlap IN (0, 1)"),
    _normalized_expression("last_alert_ok IS NULL OR last_alert_ok IN (0, 1)"),
    _normalized_expression(
        "(outcome IN ('running', 'abandoned')) = (duration_ms IS NULL)"
    ),
}


def _ddl_has_only_known_checks(sql: str) -> bool:
    checks = _check_expressions(sql)
    return (
        checks is not None
        and len(checks) == len(set(checks))
        and set(checks) == _CANONICAL_CHECKS
    )


def _ddl_has_default_conflict_and_collation(sql: str) -> bool:
    tokens = _sql_tokens(sql)
    if not tokens:
        return False
    for index, token in enumerate(tokens):
        if token == ("ident", "on") and index + 1 < len(tokens):
            if tokens[index + 1] == ("ident", "conflict"):
                if (
                    index + 2 >= len(tokens)
                    or tokens[index + 2] != ("ident", "abort")
                ):
                    return False
        if token == ("ident", "collate"):
            if index + 1 >= len(tokens) or tokens[index + 1] != ("ident", "binary"):
                return False
    return True


def _normalized_default(value: object) -> tuple[tuple[str, str], ...] | None:
    if value is None:
        return None
    tokens = _unwrap_sql_parens(_sql_tokens(str(value)))
    return _token_values(tokens)


def _ticks_columns_are_canonical(conn: sqlite3.Connection) -> bool:
    columns = conn.execute("PRAGMA table_xinfo(ticks)").fetchall()
    names = [str(row[1]).casefold() for row in columns]
    base_names = [
        "seq",
        "tick_id",
        "started_at",
        "duration_ms",
        "outcome",
        "noop",
        "overlap",
        "last_alert_ok",
    ]
    with_legacy_rowid = [
        "seq",
        "rowid",
        "tick_id",
        "started_at",
        "duration_ms",
        "outcome",
        "noop",
        "overlap",
        "last_alert_ok",
    ]
    if names not in (base_names, with_legacy_rowid):
        return False

    expected: dict[str, tuple[str, int, object, int]] = {
        "seq": ("integer", 0, None, 1),
        "tick_id": ("text", 1, None, 0),
        "started_at": ("text", 1, None, 0),
        "duration_ms": ("integer", 0, None, 0),
        "outcome": ("text", 1, "'running'", 0),
        "noop": ("integer", 1, "0", 0),
        "overlap": ("integer", 1, "0", 0),
        "last_alert_ok": ("integer", 0, None, 0),
    }
    if "rowid" in names:
        expected["rowid"] = ("text", 0, None, 0)
    for row in columns:
        name = str(row[1]).casefold()
        declared_type, not_null, default, primary_key = expected[name]
        if (
            str(row[2]).strip().casefold() != declared_type
            or int(row[3]) != not_null
            or _normalized_default(row[4]) != _normalized_default(default)
            or int(row[5]) != primary_key
            or int(row[6]) != 0
        ):
            return False
    return True


def _ticks_index_is_canonical(conn: sqlite3.Connection) -> bool:
    indexes = conn.execute("PRAGMA index_list(ticks)").fetchall()
    if len(indexes) != 1:
        return False
    index = indexes[0]
    if int(index[2]) != 1 or str(index[3]).casefold() != "u" or int(index[4]):
        return False
    escaped = str(index[1]).replace('"', '""')
    key_columns = [
        row for row in conn.execute(f'PRAGMA index_xinfo("{escaped}")')
        if int(row[5]) == 1
    ]
    return (
        len(key_columns) == 1
        and str(key_columns[0][2]).casefold() == "tick_id"
        and int(key_columns[0][3]) == 0
        and str(key_columns[0][4]).casefold() == "binary"
    )


def _trigger_is_inert(sql: str) -> bool:
    tokens = _sql_tokens(sql)
    begin = next(
        (index for index, token in enumerate(tokens) if token == ("ident", "begin")),
        None,
    )
    end = next(
        (
            index
            for index in range(len(tokens) - 1, -1, -1)
            if tokens[index] == ("ident", "end")
        ),
        None,
    )
    if begin is None or end is None or end <= begin:
        return False
    body = [token for token in tokens[begin + 1 : end] if token != ("symbol", ";")]
    return body == [("ident", "select"), ("number", "1")]


def _trigger_has_only_dml(sql: str) -> bool:
    tokens = _sql_tokens(sql)
    begin = next(
        (index for index, token in enumerate(tokens) if token == ("ident", "begin")),
        None,
    )
    end = next(
        (
            index
            for index in range(len(tokens) - 1, -1, -1)
            if tokens[index] == ("ident", "end")
        ),
        None,
    )
    if begin is None or end is None or end <= begin:
        return False

    body = tokens[begin + 1 : end]
    statements: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    for token in body:
        if token == ("symbol", ";"):
            if current:
                statements.append(current)
                current = []
        else:
            current.append(token)
    if current:
        statements.append(current)
    allowed = {
        ("ident", "insert"),
        ("ident", "update"),
        ("ident", "delete"),
    }
    return bool(statements) and all(
        statement and statement[0] in allowed for statement in statements
    )


_PROTECTED_SQL_OBJECTS = {"ticks", "latest", "sqlite_sequence"}
_PROTECTED_SQL_ACTIONS = {
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_INSERT,
    sqlite3.SQLITE_UPDATE,
    sqlite3.SQLITE_DELETE,
}


def _statement_uses_protected_objects(
    conn: sqlite3.Connection,
    statement: str,
    *,
    unmodifiable_view: str | None = None,
) -> bool:
    protected = False

    def authorize(action, first, _second, _database, _source):
        nonlocal protected
        if (
            action in _PROTECTED_SQL_ACTIONS
            and isinstance(first, str)
            and first.casefold() in _PROTECTED_SQL_OBJECTS
        ):
            protected = True
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    try:
        conn.set_authorizer(authorize)
        conn.execute(f"EXPLAIN {statement}").fetchall()
    except sqlite3.OperationalError as exc:
        if (
            unmodifiable_view is not None
            and str(exc).casefold()
            == f"cannot modify {unmodifiable_view} because it is a view".casefold()
        ):
            return False
        return True
    except sqlite3.DatabaseError:
        return True
    finally:
        conn.set_authorizer(None)
    return protected


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _trigger_target_uses_protected_objects(
    conn: sqlite3.Connection, table_name: str
) -> bool:
    target = conn.execute(
        "SELECT type FROM sqlite_schema WHERE name=? COLLATE NOCASE",
        (table_name,),
    ).fetchone()
    if target is None or str(target[0]).casefold() not in {"table", "view"}:
        return True
    unmodifiable_view = (
        table_name if str(target[0]).casefold() == "view" else None
    )

    quoted_table = _quote_identifier(table_name)
    columns = conn.execute(f"PRAGMA table_xinfo({quoted_table})").fetchall()
    writable_columns = [
        _quote_identifier(str(row[1]))
        for row in columns
        if int(row[6]) == 0
    ]
    if not writable_columns:
        return True

    assignments = ", ".join(f"{column}={column}" for column in writable_columns)
    statements = (
        f"INSERT INTO {quoted_table} DEFAULT VALUES",
        f"UPDATE {quoted_table} SET {assignments} WHERE 0",
        f"DELETE FROM {quoted_table} WHERE 0",
    )
    return any(
        _statement_uses_protected_objects(
            conn,
            statement,
            unmodifiable_view=unmodifiable_view,
        )
        for statement in statements
    )


def _triggers_are_safe(conn: sqlite3.Connection) -> bool:
    targets: set[str] = set()
    for _name, table_name, sql in conn.execute(
        "SELECT name, tbl_name, sql FROM sqlite_schema WHERE type='trigger'"
    ):
        if str(table_name).casefold() == "ticks" or not isinstance(sql, str):
            return False
        if not (_trigger_is_inert(sql) or _trigger_has_only_dml(sql)):
            return False
        targets.add(str(table_name))
    return not any(
        _trigger_target_uses_protected_objects(conn, table_name)
        for table_name in targets
    )


_LEGACY_LATEST_VIEW_SQL = """
CREATE VIEW latest AS
    SELECT seq, tick_id, started_at, duration_ms, outcome, noop, overlap, last_alert_ok
    FROM ticks
    ORDER BY seq DESC
    LIMIT 1
"""


def _view_body(sql: str) -> list[tuple[str, str]] | None:
    tokens = _sql_tokens(sql)
    as_index = next(
        (index for index, token in enumerate(tokens) if token == ("ident", "as")),
        None,
    )
    if as_index is None:
        return None
    return tokens[as_index + 1 :]


def _unrelated_view_is_safe(
    conn: sqlite3.Connection, name: str, sql: object
) -> bool:
    if not isinstance(sql, str):
        return False
    query = f"SELECT * FROM {_quote_identifier(name)} LIMIT 0"
    return not _statement_uses_protected_objects(conn, query)


def _latest_object_is_usable(conn: sqlite3.Connection) -> bool:
    latest_object = conn.execute(
        "SELECT type, sql FROM sqlite_schema WHERE name='latest' COLLATE NOCASE"
    ).fetchone()
    if latest_object is not None and str(latest_object[0]).casefold() != "view":
        return False
    views = conn.execute(
        "SELECT name, sql FROM sqlite_schema WHERE type='view'"
    ).fetchall()
    for name, view_sql in views:
        if str(name).casefold() != "latest" and not _unrelated_view_is_safe(
            conn, str(name), view_sql
        ):
            return False
    latest = latest_object
    if latest is None:
        return True
    sql = latest[1]
    if not isinstance(sql, str):
        return False
    body = _view_body(sql)
    return body is not None and tuple(body) in {
        tuple(_view_body(db._VIEW_SQL) or ()),
        tuple(_view_body(_LEGACY_LATEST_VIEW_SQL) or ()),
    }


def _sqlite_sequence_is_trustworthy(
    conn: sqlite3.Connection, maximum: int
) -> bool:
    sequence_table = conn.execute(
        "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='sqlite_sequence'"
    ).fetchone()
    if sequence_table is None:
        return maximum == 0
    try:
        rows = conn.execute(
            "SELECT name, seq, typeof(seq) FROM sqlite_sequence"
        ).fetchall()
    except sqlite3.DatabaseError:
        return False
    by_name: dict[str, list[tuple[object, object]]] = {}
    for name, sequence, value_type in rows:
        if not isinstance(name, str):
            return False
        by_name.setdefault(name.casefold(), []).append((sequence, value_type))
    if any(len(values) != 1 for values in by_name.values()):
        return False

    tick_rows = by_name.pop("ticks", [])
    if not tick_rows:
        if maximum:
            return False
        tick_sequence = 0
    else:
        sequence, value_type = tick_rows[0]
        if value_type != "integer" or not isinstance(sequence, int) or sequence < 0:
            return False
        tick_sequence = sequence
        if tick_sequence < maximum:
            return False
    if max(maximum, tick_sequence) + 1 > db.MAX_TRUSTED_SEQ:
        return False

    tables = {
        str(name).casefold(): sql
        for name, sql in conn.execute(
            "SELECT name, sql FROM sqlite_schema WHERE type='table'"
        )
        if isinstance(name, str)
    }
    for name, values in by_name.items():
        if name not in tables or name.startswith("sqlite_"):
            return False
        sql = tables[name]
        if not isinstance(sql, str) or "autoincrement" not in {
            value for kind, value in _sql_tokens(sql) if kind == "ident"
        }:
            return False
        sequence, value_type = values[0]
        if value_type != "integer" or not isinstance(sequence, int) or sequence < 0:
            return False
    return True


def _sqlite_metadata_is_recognized(conn: sqlite3.Connection) -> bool:
    tables = {
        str(name).casefold()
        for (name,) in conn.execute(
            "SELECT name FROM sqlite_schema WHERE type='table'"
        )
        if isinstance(name, str)
    }
    known_stats = {
        "sqlite_stat1": ("tbl", "idx", "stat"),
        "sqlite_stat2": ("tbl", "idx", "sampleno", "sample"),
        "sqlite_stat3": ("tbl", "idx", "neq", "nlt", "ndlt", "sample"),
        "sqlite_stat4": ("tbl", "idx", "neq", "nlt", "ndlt", "sample"),
    }
    for kind, name, _table_name in conn.execute(
        "SELECT type, name, tbl_name FROM sqlite_schema"
    ):
        if not isinstance(name, str) or not name.casefold().startswith("sqlite_"):
            continue
        folded = name.casefold()
        if folded == "sqlite_sequence":
            if str(kind).casefold() != "table":
                return False
            columns = tuple(
                str(row[1]).casefold()
                for row in conn.execute('PRAGMA table_info("sqlite_sequence")')
            )
            if columns != ("name", "seq"):
                return False
        elif folded in known_stats:
            if str(kind).casefold() != "table":
                return False
            escaped = folded.replace('"', '""')
            columns = tuple(
                str(row[1]).casefold()
                for row in conn.execute(f'PRAGMA table_info("{escaped}")')
            )
            if columns != known_stats[folded]:
                return False
            for (table_name,) in conn.execute(
                f'SELECT DISTINCT tbl FROM "{escaped}"'
            ):
                if (
                    not isinstance(table_name, str)
                    or table_name.casefold() not in tables
                ):
                    return False
        elif folded.startswith("sqlite_autoindex_"):
            continue
        else:
            return False
    return True


def _ticks_schema_is_trustworthy(conn: sqlite3.Connection) -> bool:
    table = next(
        (
            row
            for row in conn.execute("PRAGMA table_list").fetchall()
            if str(row[1]).casefold() == "ticks"
        ),
        None,
    )
    if table is None or str(table[2]).casefold() != "table" or bool(table[4]):
        return False
    if len(table) > 5 and bool(table[5]):
        return False
    schema_row = conn.execute(
        "SELECT type, sql FROM sqlite_schema WHERE name='ticks' COLLATE NOCASE"
    ).fetchone()
    if (
        schema_row is None
        or str(schema_row[0]).casefold() != "table"
        or not isinstance(schema_row[1], str)
    ):
        return False
    sql = schema_row[1]
    tokens = _sql_tokens(sql)
    if (
        not tokens
        or not _ticks_columns_are_canonical(conn)
        or not _ticks_index_is_canonical(conn)
        or conn.execute("PRAGMA foreign_key_list(ticks)").fetchall()
        or not _ddl_has_only_known_checks(sql)
        or not _ddl_has_default_conflict_and_collation(sql)
        or "autoincrement"
        not in {value for kind, value in tokens if kind == "ident"}
    ):
        return False

    maximum_row = conn.execute("SELECT MAX(seq) FROM ticks").fetchone()
    maximum = (
        0
        if maximum_row is None or maximum_row[0] is None
        else int(maximum_row[0])
    )
    return _sqlite_sequence_is_trustworthy(conn, maximum)


def _schema_is_trustworthy(conn: sqlite3.Connection) -> bool:
    if not _ticks_schema_is_trustworthy(conn):
        return False
    return (
        _sqlite_metadata_is_recognized(conn)
        and _latest_object_is_usable(conn)
        and _triggers_are_safe(conn)
    )


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
                    structurally_trusted = (
                        check is not None
                        and str(check[0]).lower() == "ok"
                        and _schema_is_trustworthy(conn)
                    )
                    corrupt = not structurally_trusted
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
    parser.add_argument(
        "--acknowledge-wal-loss",
        action="store_true",
        help="archive an unresolved repair intent after confirmed WAL data loss",
    )
    args = parser.parse_args(argv)

    state_dir = args.state_dir.resolve()
    if args.acknowledge_wal_loss:
        try:
            moved, orphan = db.acknowledge_missing_wal_loss(state_dir)
        except (OSError, StoreUnavailableError) as exc:
            print(f"repair: blocked: {exc}", file=sys.stderr)
            return 2
        print(
            "repair: WAL data is unrecoverable; "
            f"intent quarantined as {orphan.name}; archived main preserved at "
            f"{moved.name}; the next start will create a fresh store"
        )
        return 0

    try:
        quarantined_before = _orphaned_intents(state_dir)
        moved = repair_store(state_dir)
        quarantined = _orphaned_intents(state_dir) - quarantined_before
    except db._RepairIntentWalMissingError as exc:
        print(
            "repair: blocked: expected WAL missing at source and target; "
            f"intent retained; target={exc.target.name}",
            file=sys.stderr,
        )
        return 2
    except (StoreUnavailableError, sqlite3.OperationalError, OSError) as exc:
        print(
            f"repair: blocked: {exc}",
            file=sys.stderr,
        )
        return 2

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
