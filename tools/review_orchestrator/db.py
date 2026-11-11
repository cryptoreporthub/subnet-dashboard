"""SQLite store for review-orchestrator ticks: one writer, one reader view.

The writer (run_tick) never reads an incumbent heartbeat to decide whether to
publish. `latest` is recomputed by the reader as MAX(seq), so a corrupt or
bogus incumbent cannot block a newer tick. This replaces the v0 per-tick file
store whose `seq/` reservation and `heartbeat/latest.json` comparison were the
round-3 blockers.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

DB_FILENAME = "orchestrator.sqlite"
BUSY_TIMEOUT_MS = 5000
#: A hand-written seq above this would pin the AUTOINCREMENT counter for the
#: life of the store; fail loudly instead of silently jamming every later tick.
MAX_TRUSTED_SEQ = 2 ** 62

COLUMNS = (
    "seq, tick_id, started_at, duration_ms, outcome, noop, overlap, last_alert_ok"
)

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ticks (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    tick_id       TEXT    NOT NULL UNIQUE,
    started_at    TEXT    NOT NULL CHECK (length(started_at) BETWEEN 20 AND 40),
    duration_ms   INTEGER          CHECK (duration_ms IS NULL OR duration_ms >= 0),
    outcome       TEXT    NOT NULL DEFAULT 'running'
                          CHECK (outcome IN ('running', 'completed', 'failed', 'abandoned')),
    noop          INTEGER NOT NULL DEFAULT 0 CHECK (noop    IN (0, 1)),
    overlap       INTEGER NOT NULL DEFAULT 0 CHECK (overlap IN (0, 1)),
    last_alert_ok INTEGER          CHECK (last_alert_ok IS NULL OR last_alert_ok IN (0, 1)),
    CHECK ((outcome IN ('running', 'abandoned')) = (duration_ms IS NULL))
)
"""

# Dropped and recreated on every connect so a schema change cannot leave a
# stale view definition pinned in an existing store.
_VIEW_DROP_SQL = "DROP VIEW IF EXISTS latest"

_VIEW_SQL = """
CREATE VIEW latest AS
    SELECT seq, tick_id, started_at, duration_ms, outcome, noop, overlap, last_alert_ok
    FROM ticks
    ORDER BY seq DESC
    LIMIT 1
"""


class StoreError(RuntimeError):
    """Base for a store that refuses to open in the caller's environment.

    `repair` helps only the corrupt branch; the rest need the access fixed. Any
    reader that wants every open failure names this one type, so a store error
    added later cannot slip past its except clause.
    """


class StoreCorruptError(StoreError):
    """The state directory holds something that is not a usable store.

    Recover with `tools.review_orchestrator.persist repair --state-dir <dir>`.
    """


class StoreUnavailableError(StoreError):
    """The store cannot be opened, but its bytes may be perfectly fine.

    A missing permission, a read-only directory, or a filesystem that cannot do
    WAL. Unlike StoreCorruptError, `repair` cannot help: fix the access and
    retry.
    """


#: sqlite messages that mean the bytes on disk are not a database. Everything
#: else is access, contention, or I/O, and must not be reported as corruption.
_CORRUPT_MARKERS = ("not a database", "malformed")


def _store_error(exc: sqlite3.Error, path: Path) -> Exception:
    text = str(exc).lower()
    if any(marker in text for marker in _CORRUPT_MARKERS):
        return StoreCorruptError(f"{path}: {exc}")
    return StoreUnavailableError(f"{path}: {exc}")


class DuplicateTickIdError(ValueError):
    """Caller-supplied tick_id is already present in this store."""


@dataclass(frozen=True)
class StartedTick:
    seq: int
    overlap: bool


def db_path(state_dir: Path) -> Path:
    return Path(state_dir) / DB_FILENAME


def connect(state_dir: Path) -> sqlite3.Connection:
    """Open (creating if absent) the store and bring the schema up to date."""
    path = db_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(
            str(path), isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000
        )
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        _ensure_wal(conn)
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute(_TABLE_SQL)
        _ensure_view(conn)
        conn.execute(f"SELECT {COLUMNS} FROM latest LIMIT 1").fetchone()
    except sqlite3.OperationalError as exc:
        # Contention is transient: the caller retries, it does not repair.
        text = str(exc).lower()
        if "locked" in text or "busy" in text:
            raise
        raise _store_error(exc, path) from exc
    except sqlite3.DatabaseError as exc:
        raise _store_error(exc, path) from exc
    return conn


def _ensure_wal(conn: sqlite3.Connection, *, attempts: int = 200) -> None:
    """Enable WAL, retrying while another connection holds the store.

    Converting the journal mode needs an exclusive lock and does not invoke the
    busy handler, so a concurrent writer returns SQLITE_BUSY immediately. The
    winner converts the store; losers see WAL on the next look.
    """
    for _ in range(attempts):
        if str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal":
            return
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError:
            time.sleep(0.005)
    raise sqlite3.OperationalError("could not enable WAL")


def _squash(sql: str) -> str:
    return " ".join(sql.split())


def _ensure_view(conn: sqlite3.Connection) -> None:
    """Keep the reader view current without rewriting it on every connect.

    A DROP/CREATE on every connect would take a write lock against a running
    tick; rewrite only when the stored definition actually differs.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'view' AND name = 'latest'"
    ).fetchone()
    if row is not None and _squash(row[0]) == _squash(_VIEW_SQL):
        return
    # Rewrite only when the definition differs, and hold a write lock so two
    # writers racing on a fresh store cannot both DROP/CREATE the view.
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'view' AND name = 'latest'"
        ).fetchone()
        if row is None or _squash(row[0]) != _squash(_VIEW_SQL):
            conn.execute(_VIEW_DROP_SQL)
            conn.execute(_VIEW_SQL)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


@contextmanager
def _immediate(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def start_tick(
    conn: sqlite3.Connection,
    tick_id: str,
    started_at: str,
    *,
    cutoff_iso: str,
) -> StartedTick:
    """Sweep stale running rows, measure overlap, and open a new running row."""
    with _immediate(conn):
        highest = int(conn.execute("SELECT COALESCE(MAX(seq), 0) FROM ticks").fetchone()[0])
        if highest > MAX_TRUSTED_SEQ:
            raise StoreCorruptError(
                f"seq {highest} exceeds the trusted maximum {MAX_TRUSTED_SEQ}"
            )
        conn.execute(
            "UPDATE ticks SET outcome = 'abandoned' "
            "WHERE outcome = 'running' AND started_at < ?",
            (cutoff_iso,),
        )
        overlap = int(
            conn.execute(
                "SELECT EXISTS(SELECT 1 FROM ticks WHERE outcome = 'running')"
            ).fetchone()[0]
        )
        try:
            cursor = conn.execute(
                "INSERT INTO ticks (tick_id, started_at, overlap) VALUES (?, ?, ?)",
                (tick_id, started_at, overlap),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateTickIdError(tick_id) from exc
        seq = int(cursor.lastrowid)
    return StartedTick(seq=seq, overlap=bool(overlap))


def complete_tick(
    conn: sqlite3.Connection,
    seq: int,
    *,
    outcome: str,
    duration_ms: int,
    noop: bool,
    last_alert_ok: bool | None = None,
) -> None:
    """Move a running row to a terminal outcome. A replay (duration already set)
    is a no-op, so a retried completion cannot rewrite history."""
    if outcome not in ("completed", "failed"):
        raise ValueError(f"terminal outcome required, got {outcome!r}")
    with _immediate(conn):
        conn.execute(
            "UPDATE ticks SET outcome = ?, duration_ms = ?, noop = ?, last_alert_ok = ? "
            "WHERE seq = ? AND duration_ms IS NULL",
            (
                outcome,
                int(duration_ms),
                1 if noop else 0,
                None if last_alert_ok is None else int(last_alert_ok),
                int(seq),
            ),
        )


def latest_row(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(f"SELECT {COLUMNS} FROM latest").fetchone()
