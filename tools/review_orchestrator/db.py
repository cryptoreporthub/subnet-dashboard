"""SQLite store for review-orchestrator ticks: one writer, one reader view.

The writer (run_tick) never reads an incumbent heartbeat to decide whether to
publish. `latest` is recomputed by the reader as MAX(seq), so a corrupt or
bogus incumbent cannot block a newer tick. This replaces the v0 per-tick file
store whose `seq/` reservation and `heartbeat/latest.json` comparison were the
round-3 blockers.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import secrets
import sqlite3
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

DB_FILENAME = "orchestrator.sqlite"
REPAIR_INTENT_FILENAME = ".orchestrator-repair-intent.json"
BUSY_TIMEOUT_MS = 5000
WAL_CONVERSION_TIMEOUT_MS = 300
WAL_CONVERSION_BUSY_TIMEOUT_MS = 25
#: Shared-lock budget for a reader connection (`locked_connect`).
STORE_LOCK_TIMEOUT_SECONDS = 2.0
#: The dead-man read is a liveness check: it must never inherit the writer
#: budget, or a wedged writer would hang the very thing watching for it.
DEADMAN_LOCK_TIMEOUT_SECONDS = 2.0
#: Exclusive repair/writer acquisition waits for a tick to finish. A tick can
#: legitimately run for minutes, so this matches the tick lifecycle rather than
#: the 2s read budget that made repair fail spuriously.
WRITER_LOCK_TIMEOUT_SECONDS = 600.0
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
    SELECT seq AS seq, tick_id AS tick_id, started_at AS started_at,
           duration_ms AS duration_ms, outcome AS outcome, noop AS noop,
           overlap AS overlap, last_alert_ok AS last_alert_ok
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


class _RepairIntentStateError(StoreUnavailableError):
    """A stale or ambiguous intent that the explicit repair path can quarantine."""


class _RepairIntentWalMissingError(StoreUnavailableError):
    """A listed WAL is missing from both locations; keep the intent unresolved."""

    def __init__(self, target: Path) -> None:
        self.target = target
        super().__init__(
            f"expected WAL missing at source and target for repair target {target.name}"
        )


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


def _repair_intent_path(state_dir: Path) -> Path:
    return Path(state_dir) / REPAIR_INTENT_FILENAME


def _fsync_directory(state_dir: Path) -> None:
    descriptor = os.open(state_dir, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _path_kind(path: Path) -> str:
    """"regular", "absent", or "other" — never follows a symlink.

    `Path.is_file()` follows symlinks, so a symlink planted at the pending main
    target would be reported as a completed move. lstat refuses to follow.
    """
    try:
        mode = os.lstat(path).st_mode
    except (OSError, ValueError):
        return "absent"
    return "regular" if stat.S_ISREG(mode) else "other"


def _validate_intent_target(target_name: object) -> None:
    if (
        not isinstance(target_name, str)
        or Path(target_name).name != target_name
        or not target_name.startswith(f"{DB_FILENAME}.corrupt-")
    ):
        raise _RepairIntentStateError("invalid repair intent target")
    # A NUL byte cannot name a file: it raises ValueError at rename time, which
    # would escape every StoreError handler. Treat it as corrupt intent.
    if "\x00" in target_name:
        raise _RepairIntentStateError(
            "invalid repair intent target: embedded NUL byte"
        )


def _read_repair_intent_locked(
    state_dir: Path,
) -> tuple[Path, str, list[str]] | None:
    intent = _repair_intent_path(state_dir)
    if not intent.exists():
        return None
    try:
        document = json.loads(intent.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _RepairIntentStateError(
            f"invalid repair intent {intent}: {exc}"
        ) from exc

    if not isinstance(document, dict):
        raise _RepairIntentStateError(f"invalid repair intent {intent}")
    target_name = document.get("target")
    files = document.get("files")
    if (
        document.get("version") != 1
        or not isinstance(files, list)
        or "main" not in files
        or any(
            not isinstance(item, str) or item not in {"main", "wal", "shm"}
            for item in files
        )
        or len(files) != len(set(files))
    ):
        raise _RepairIntentStateError(f"invalid repair intent {intent}")
    try:
        _validate_intent_target(target_name)
    except _RepairIntentStateError as exc:
        raise _RepairIntentStateError(f"invalid repair intent {intent}: {exc}") from exc
    return intent, target_name, files


def _recover_repair_intent_locked(state_dir: Path) -> Path | None:
    parsed = _read_repair_intent_locked(state_dir)
    if parsed is None:
        return None
    intent, target_name, files = parsed

    main = db_path(state_dir)
    moved = Path(state_dir) / target_name
    source = {
        "main": main,
        "wal": Path(f"{main}-wal"),
        "shm": Path(f"{main}-shm"),
    }
    destination = {
        "main": moved,
        "wal": Path(f"{moved}-wal"),
        "shm": Path(f"{moved}-shm"),
    }

    # An intent that omits a sidecar sitting on disk would strand it beside a
    # database that is no longer the one it belongs to; committed-but-
    # uncheckpointed WAL rows would then be silently dropped. Fail closed.
    for name in ("wal", "shm"):
        if name in files:
            continue
        if _path_kind(source[name]) != "absent":
            raise _RepairIntentStateError(
                f"repair intent omits a sidecar present on disk: {source[name]}"
            )
        if _path_kind(destination[name]) != "absent":
            raise _RepairIntentStateError(
                f"repair intent omits a sidecar present on disk: {destination[name]}"
            )

    moves = []
    for name in ("main", "wal", "shm"):
        if name not in files:
            continue
        original = source[name]
        target = destination[name]
        if name == "main":
            original_kind = _path_kind(original)
            target_kind = _path_kind(target)
            if original_kind == "other":
                raise StoreUnavailableError(
                    f"repair main database is not a regular file: {original}"
                )
            if target_kind == "other":
                raise StoreUnavailableError(
                    f"repair main database is not a regular file: {target}"
                )
            original_is_file = original_kind == "regular"
            target_is_file = target_kind == "regular"
            if not original_is_file and not target_is_file:
                raise StoreUnavailableError(
                    f"repair main database is missing from both {original} and {target}"
                )
            if original_is_file and target_is_file:
                raise _RepairIntentStateError(
                    f"ambiguous repair state: both {original} and {target} exist"
                )
            if original_is_file:
                moves.append((original, target))
            continue
        original_kind = _path_kind(original)
        target_kind = _path_kind(target)
        if original_kind == "other" or target_kind == "other":
            raise StoreUnavailableError(
                f"repair sidecar is not a regular file: "
                f"{original if original_kind == 'other' else target}"
            )
        if original_kind == "regular" and target_kind == "regular":
            raise _RepairIntentStateError(
                f"ambiguous repair state: both {original} and {target} exist"
            )
        if original_kind == "regular":
            moves.append((original, target))
        elif target_kind == "regular":
            continue
        elif name == "wal":
            raise _RepairIntentWalMissingError(moved)

    try:
        for original, target in moves:
            original.replace(target)
            _fsync_directory(Path(state_dir))
        intent.unlink()
        _fsync_directory(Path(state_dir))
    except OSError as exc:
        raise StoreUnavailableError(f"repair recovery {intent}: {exc}") from exc
    return moved


def acknowledge_missing_wal_loss(state_dir: Path) -> tuple[Path, Path]:
    """Quarantine only a validated intent with an irrecoverably missing WAL."""
    state_dir = Path(state_dir)
    with store_lock(state_dir, exclusive=True, recover_intent=False):
        parsed = _read_repair_intent_locked(state_dir)
        if parsed is None:
            raise StoreUnavailableError("no pending repair intent to acknowledge")
        _, target_name, files = parsed
        if "wal" not in files:
            raise StoreUnavailableError(
                "WAL loss acknowledgement requires a manifest-listed WAL"
            )
        main = db_path(state_dir)
        moved = state_dir / target_name
        source = {
            "main": main,
            "wal": Path(f"{main}-wal"),
            "shm": Path(f"{main}-shm"),
        }
        destination = {
            "main": moved,
            "wal": Path(f"{moved}-wal"),
            "shm": Path(f"{moved}-shm"),
        }
        for name in ("wal", "shm"):
            if name not in files:
                if (
                    _path_kind(source[name]) != "absent"
                    or _path_kind(destination[name]) != "absent"
                ):
                    raise StoreUnavailableError(
                        "WAL loss acknowledgement refused: unlisted sidecar exists"
                    )
        if (
            _path_kind(source["main"]) != "absent"
            or _path_kind(destination["main"]) != "regular"
            or _path_kind(source["wal"]) != "absent"
            or _path_kind(destination["wal"]) != "absent"
            or _path_kind(source["shm"]) != "absent"
            or _path_kind(destination["shm"]) not in {"regular", "absent"}
        ):
            raise StoreUnavailableError(
                "WAL loss acknowledgement requires a moved main and missing WAL"
            )
        orphan = _quarantine_repair_intent_locked(state_dir)
        if orphan is None:
            raise StoreUnavailableError(
                "repair intent disappeared during acknowledgement"
            )
        return moved, orphan


def _quarantine_repair_intent_locked(state_dir: Path) -> Path | None:
    """Preserve an unusable intent without blocking explicit store repair."""
    intent = _repair_intent_path(state_dir)
    if not intent.exists():
        return None
    quarantined = intent.with_name(
        f"{intent.name}.orphan-{secrets.token_hex(8)}"
    )
    try:
        os.replace(intent, quarantined)
        _fsync_directory(Path(state_dir))
    except OSError as exc:
        raise StoreUnavailableError(f"cannot quarantine repair intent {intent}: {exc}") from exc
    return quarantined


def _recover_or_quarantine_repair_intent_locked(state_dir: Path) -> Path | None:
    """Return a completed move target, or quarantine an invalid intent."""
    try:
        return _recover_repair_intent_locked(state_dir)
    except _RepairIntentStateError:
        _quarantine_repair_intent_locked(state_dir)
        return None


def _write_repair_intent(
    state_dir: Path, moved: Path, files: list[str]
) -> None:
    intent = _repair_intent_path(state_dir)
    temporary = Path(f"{intent}.{secrets.token_hex(8)}.tmp")
    payload = {"version": 1, "target": moved.name, "files": files}
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, intent)
        _fsync_directory(state_dir)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def move_store_aside(path: Path, moved: Path) -> Path:
    """Start and finish a recoverable move while the caller holds the write lock."""
    state_dir = path.parent
    if _repair_intent_path(state_dir).exists():
        raise StoreUnavailableError(f"repair already pending in {state_dir}")
    source = {
        "main": path,
        "wal": Path(f"{path}-wal"),
        "shm": Path(f"{path}-shm"),
    }
    destination = {
        "main": moved,
        "wal": Path(f"{moved}-wal"),
        "shm": Path(f"{moved}-shm"),
    }
    existing_targets = [target for target in destination.values() if target.exists()]
    if existing_targets:
        raise StoreUnavailableError(
            f"repair target already exists: {existing_targets[0]}"
        )
    files = [name for name, source_path in source.items() if source_path.exists()]
    if "main" not in files:
        raise StoreUnavailableError(f"store disappeared before repair: {path}")
    _write_repair_intent(state_dir, moved, files)
    _recover_repair_intent_locked(state_dir)
    return moved


def _acquire_store_lock(
    descriptor: int,
    state_dir: Path,
    mode: int,
    *,
    recover_intent: bool = True,
    timeout_seconds: float | None = None,
) -> None:
    budget = (
        STORE_LOCK_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    )
    deadline = time.monotonic() + budget

    def acquire(lock_mode: int) -> None:
        while True:
            try:
                fcntl.flock(descriptor, lock_mode | fcntl.LOCK_NB)
                return
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                    raise StoreUnavailableError(
                        f"cannot acquire store lock in {state_dir}: {exc}"
                    ) from exc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise StoreUnavailableError(
                        f"timed out acquiring store lock in {state_dir}"
                    ) from exc
                time.sleep(min(0.01, remaining))

    acquire(mode)
    try:
        if recover_intent and _repair_intent_path(state_dir).exists():
            if mode == fcntl.LOCK_SH:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                acquire(fcntl.LOCK_EX)
            _recover_repair_intent_locked(state_dir)
            if mode == fcntl.LOCK_SH:
                acquire(fcntl.LOCK_SH)
    except BaseException:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        raise


@contextmanager
def store_lock(
    state_dir: Path,
    *,
    exclusive: bool = False,
    recover_intent: bool = True,
    timeout_seconds: float | None = None,
) -> Iterator[None]:
    """Coordinate production store users and repair through the directory inode.

    An exclusive lease waits for the tick lifecycle; a shared read (the dead-man)
    is bounded so a wedged writer cannot hang the check that watches it.
    """
    descriptor = os.open(Path(state_dir), os.O_RDONLY)
    if timeout_seconds is None:
        timeout_seconds = (
            WRITER_LOCK_TIMEOUT_SECONDS if exclusive else DEADMAN_LOCK_TIMEOUT_SECONDS
        )
    locked = False
    try:
        _acquire_store_lock(
            descriptor,
            Path(state_dir),
            fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
            recover_intent=recover_intent,
            timeout_seconds=timeout_seconds,
        )
        locked = True
        yield
    finally:
        try:
            if locked:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


@contextmanager
def locked_connect(state_dir: Path) -> Iterator[sqlite3.Connection]:
    """Hold a shared store lease for the full lifetime of a connection."""
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(state_dir, os.O_RDONLY)
    conn = None
    try:
        _acquire_store_lock(descriptor, state_dir, fcntl.LOCK_SH)
        if not db_path(state_dir).is_file():
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            _acquire_store_lock(
                descriptor,
                state_dir,
                fcntl.LOCK_EX,
                timeout_seconds=WRITER_LOCK_TIMEOUT_SECONDS,
            )
            conn = connect(state_dir)
            fcntl.flock(descriptor, fcntl.LOCK_SH)
        else:
            conn = connect(state_dir)
        yield conn
    finally:
        try:
            if conn is not None:
                conn.close()
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def connect(state_dir: Path) -> sqlite3.Connection:
    """Open (creating if absent) the store and bring the schema up to date."""
    path = db_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = None
    try:
        conn = sqlite3.connect(
            str(path), isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000
        )
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {WAL_CONVERSION_BUSY_TIMEOUT_MS}")
        _ensure_wal(conn)
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute(_TABLE_SQL)
        _ensure_view(conn)
        conn.execute(f"SELECT {COLUMNS} FROM latest LIMIT 1").fetchone()
    except sqlite3.OperationalError as exc:
        _close_after_setup_failure(conn)
        # Contention is transient: the caller retries, it does not repair.
        if _is_busy_or_locked(exc):
            raise
        raise _store_error(exc, path) from exc
    except sqlite3.DatabaseError as exc:
        _close_after_setup_failure(conn)
        raise _store_error(exc, path) from exc
    except BaseException:
        _close_after_setup_failure(conn)
        raise
    return conn


def _close_after_setup_failure(conn: sqlite3.Connection | None) -> None:
    if conn is None:
        return
    try:
        conn.close()
    except sqlite3.Error:
        pass


def _is_busy_or_locked(exc: sqlite3.OperationalError) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(code, int):
        primary_code = code & 0xFF
        return primary_code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    text = str(exc).lower()
    return "locked" in text or "busy" in text


def _ensure_wal(
    conn: sqlite3.Connection,
    *,
    attempts: int = 200,
    timeout_ms: int = WAL_CONVERSION_TIMEOUT_MS,
) -> None:
    """Enable WAL, retrying while another connection holds the store.

    Converting the journal mode needs an exclusive lock and does not invoke the
    busy handler on every SQLite build, so retries are limited to busy/locked
    errors and bounded by a monotonic deadline.
    """
    if attempts < 1 or timeout_ms < 0:
        raise ValueError("attempts must be positive and timeout_ms non-negative")
    deadline = time.monotonic() + timeout_ms / 1000
    last_error = None
    for _ in range(attempts):
        try:
            if str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal":
                return
            conn.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as exc:
            if not _is_busy_or_locked(exc):
                raise
            last_error = exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(0.005, remaining))
    if last_error is not None:
        raise last_error
    raise sqlite3.OperationalError("WAL conversion did not complete")


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
        highest = int(
            conn.execute("SELECT COALESCE(MAX(seq), 0) FROM ticks").fetchone()[0]
        )
        try:
            sequences = conn.execute(
                "SELECT seq, typeof(seq) FROM sqlite_sequence "
                "WHERE name = 'ticks' COLLATE NOCASE"
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise StoreCorruptError(
                f"ticks sequence metadata is unreadable: {exc}"
            ) from exc
        if len(sequences) > 1:
            raise StoreCorruptError("ticks has duplicate sqlite_sequence rows")
        if not sequences:
            if highest:
                raise StoreCorruptError(
                    "ticks rows exist but sqlite_sequence has no ticks entry"
                )
            sequence = 0
        else:
            sequence_value, value_type = sequences[0]
            if value_type != "integer" or not isinstance(sequence_value, int):
                raise StoreCorruptError("ticks sqlite_sequence value is not an integer")
            sequence = sequence_value
        next_sequence = max(highest, sequence) + 1
        if sequence < highest:
            raise StoreCorruptError(
                f"ticks sqlite_sequence {sequence} is behind the highest row {highest}"
            )
        if next_sequence > MAX_TRUSTED_SEQ:
            raise StoreCorruptError(
                f"next seq {next_sequence} exceeds the trusted maximum "
                f"{MAX_TRUSTED_SEQ}"
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
            # Only a tick_id collision is a duplicate. A CHECK or NOT NULL
            # failure is a store defect and must not be mislabelled.
            if not conn.execute(
                "SELECT 1 FROM ticks WHERE tick_id = ? LIMIT 1", (tick_id,)
            ).fetchone():
                raise
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
