"""ledger.db: learned weights and the keys that say which effect already applied.

One SQLite file beside soul_map.json. Rollback journal (journal_mode=DELETE) with
synchronous=FULL, because production runs two processes on the volume and the
SQLite in the image is inside the WAL-reset bug range. Every write runs in
BEGIN IMMEDIATE, so a read-then-write transaction never fails mid-way on a lock upgrade.

First use imports today's values from soul_map.json (read-only). A missing soul_map
seeds defaults. A soul_map that cannot be read refuses, and nothing is written.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

DEFAULT_SOUL_MAP_PATH = os.path.join("data", "soul_map.json")
LEDGER_DB_ENV = "LEDGER_DB_PATH"
# The weights gate anchors the default soul_map to the repo root so it does not depend on cwd.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REPO_SOUL_MAP = os.path.join(_REPO_ROOT, "data", "soul_map.json")
BUSY_TIMEOUT_MS = 5000

SOUL_MAP_MARKER = "imported:soul_map"
# Root key of soul_map.json, written in the same locked write that drops the imported weight
# keys. Once it is there the weights exist nowhere but ledger.db, so a ledger that is missing
# or lacks its import row must refuse. Seeding defaults would silently discard the learning.
MIGRATED_KEY = "weights_ledger_migrated"
PUMP_MARKER = "imported:pump_calibration"

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS weights ("
    "kind TEXT NOT NULL, name TEXT NOT NULL, value REAL NOT NULL, updated_at TEXT NOT NULL, "
    "PRIMARY KEY (kind, name)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS weight_applied ("
    "source_id TEXT NOT NULL, effect TEXT NOT NULL, value_before REAL, value_after REAL, "
    "applied_at TEXT NOT NULL, PRIMARY KEY (source_id, effect)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS ledger_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID",
)


class LedgerUnreadable(RuntimeError):
    """ledger.db, or the file it must import from, cannot be read. Nothing was written."""


class SoulMapUnreadable(LedgerUnreadable):
    """soul_map.json exists but is corrupt or unreadable, so there is nothing safe to import."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ledger_path_for(anchor_path: Optional[str] = None, *, derived: bool = False) -> str:
    """ledger.db beside the soul_map at ``anchor_path``.

    ``soul_map.json`` gets ``ledger.db``. A soul_map under another name gets its own
    ``<name>.ledger.db``, so two soul_map files in one directory never share weights.
    LEDGER_DB_PATH redirects the repo's own data/soul_map.json only (a relative default counts
    when the cwd is the repo root), so a test in a temporary directory keeps its own ledger.
    ``derived=True`` ignores that override.
    """
    anchor = os.path.abspath(anchor_path or DEFAULT_SOUL_MAP_PATH)
    if anchor == os.path.abspath(DEFAULT_SOUL_MAP_PATH) and os.path.abspath(os.getcwd()) == _REPO_ROOT:
        anchor = _REPO_SOUL_MAP
    directory, base = os.path.split(anchor)
    override = os.environ.get(LEDGER_DB_ENV, "").strip()
    if override and anchor == _REPO_SOUL_MAP and not derived:
        return override
    return os.path.join(directory, "ledger.db" if base == "soul_map.json" else base + ".ledger.db")


def pump_anchor(calibration_path: str) -> str:
    """The soul_map path whose ledger holds the blend weights beside ``calibration_path``."""
    return os.path.join(os.path.dirname(os.path.abspath(calibration_path)), "soul_map.json")


def connect(db_path: str) -> sqlite3.Connection:
    """Own connection: explicit transactions, rollback journal, full fsync."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    try:
        conn = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000.0, isolation_level=None)
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=FULL")
    except sqlite3.Error as exc:
        raise LedgerUnreadable(f"ledger.db unavailable at {db_path}: {exc}") from exc
    return conn


_ready_lock = threading.Lock()
_ready: set = set()
_seeded_missing: set = set()


def _identity(db_path: str, marker: str) -> Optional[tuple]:
    try:
        st = os.stat(db_path)
    except OSError:
        return None
    return (os.path.abspath(db_path), st.st_dev, st.st_ino, marker)


def _ensure(
    db_path: str,
    marker: str,
    seed: Callable[[sqlite3.Connection], str],
    source_path: str,
    soul_map_path: str,
) -> None:
    """Create the schema and run ``seed`` once. A ledger seeded while its source file was
    missing and never written since imports the source when it appears.

    Raises LedgerUnreadable when ``soul_map_path`` carries the migrated marker but the ledger
    is missing or holds no soul_map import row: the weights were dropped from soul_map, so
    nothing is left to re-import."""
    key = _identity(db_path, marker)
    if key is not None and key in _ready and not (key in _seeded_missing and os.path.exists(source_path)):
        return
    if key is None and _soul_map_migrated(soul_map_path):
        raise LedgerUnreadable(_MIGRATED_REFUSAL.format(db=db_path))
    conn = connect(db_path)
    state = ""
    try:
        try:
            conn.execute("BEGIN IMMEDIATE")
            for statement in _SCHEMA:
                conn.execute(statement)
            row = conn.execute("SELECT value FROM ledger_meta WHERE key=?", (marker,)).fetchone()
            soul_row = row if marker == SOUL_MAP_MARKER else conn.execute(
                "SELECT 1 FROM ledger_meta WHERE key=?", (SOUL_MAP_MARKER,)
            ).fetchone()
            if soul_row is None and _soul_map_migrated(soul_map_path):
                raise LedgerUnreadable(_MIGRATED_REFUSAL.format(db=db_path))
            run = row is None
            if row is not None and os.path.exists(source_path):
                untouched = conn.execute("SELECT 1 FROM weight_applied LIMIT 1").fetchone() is None
                run = untouched and json.loads(row[0]).get("state") == "missing"
            state = json.loads(row[0]).get("state", "") if row is not None else ""
            if run:
                state = seed(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO ledger_meta(key, value) VALUES (?, ?)",
                    (marker, json.dumps({"state": state, "at": now_iso()})),
                )
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            _rollback(conn)
            raise LedgerUnreadable(f"ledger.db unusable at {db_path}: {exc}") from exc
        except BaseException:
            _rollback(conn)
            raise
    finally:
        conn.close()
    key = _identity(db_path, marker)
    if key is not None:
        with _ready_lock:
            _ready.add(key)
            if state == "missing":
                _seeded_missing.add(key)
            else:
                _seeded_missing.discard(key)
    if marker == SOUL_MAP_MARKER and state == "loaded" and db_path == ledger_path_for(source_path, derived=True):
        _drop_imported_keys(source_path)


_MIGRATED_REFUSAL = (
    "ledger.db at {db} is missing or has no soul_map import row, but soul_map.json says the "
    "weights moved there. Restore ledger.db from backup; defaults would discard the learned weights."
)


def _soul_map_migrated(soul_map_path: str) -> bool:
    """True when soul_map.json carries the migrated marker. A missing file has none.
    A file that cannot be read cannot be ruled out, so it refuses."""
    from internal.store.soul_map_io import _read_for_write

    read = _read_for_write(soul_map_path)
    if read.kind == "missing":
        return False
    if read.kind == "loaded" and isinstance(read.blob, dict):
        return MIGRATED_KEY in read.blob
    raise SoulMapUnreadable(f"soul_map {read.kind} at {soul_map_path}: {read.error}")


# soul_map keys whose values now live in ledger.db. scripts/compact_soul_map.py insists the root
# expert_weights and the adversarial_state container stay present, so those two stay (the mirror
# is frozen at the import and nothing reads it but a rollback).
_DROPPED_ADVERSARIAL_KEYS = (
    "council_weights",
    "signal_weights",
    "impact_strength",
    "last_weight_update",
    "last_impact_strength_update",
)


def _drop_imported_keys(soul_map_path: str) -> None:
    """Remove the imported weight keys once ledger.db committed them. Every other key is left as is.

    Idempotent: a crash after the ledger commit and before this write only leaves the keys
    in place, and the next first use drops them. Skipped when LEDGER_DB_PATH redirected the
    ledger, so a test run cannot strip the developer's real soul_map.
    """
    from internal.store.soul_map_io import WriteOutcome, write_soul_map

    marker = {"ledger": os.path.basename(ledger_path_for(soul_map_path, derived=True))}

    def mutate(blob: Dict[str, Any]) -> None:
        blob.setdefault(MIGRATED_KEY, marker)
        blob.pop("judge_weights", None)
        adv = blob.get("adversarial_state")
        if isinstance(adv, dict):
            for key in _DROPPED_ADVERSARIAL_KEYS:
                adv.pop(key, None)

    try:
        result = write_soul_map(mutate, path=soul_map_path, raise_on_lock_timeout=False)
    except Exception:
        logger.exception("could not drop imported weight keys from %s", soul_map_path)
        return
    if result.outcome not in (WriteOutcome.APPLIED, WriteOutcome.DECLINED):
        logger.warning("imported weight keys stay in %s: %s", soul_map_path, result.outcome.value)


def _rollback(conn: sqlite3.Connection) -> None:
    try:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def _seed_weights_from_soul_map(soul_map_path: str) -> Callable[[sqlite3.Connection], str]:
    def seed(conn: sqlite3.Connection) -> str:
        from internal.council import weights as council
        from internal.judges import weights as judges
        from internal.council.scorer_identity import finite_number
        from internal.store.soul_map_io import _read_for_write

        read = _read_for_write(soul_map_path)
        if read.kind == "missing":
            blob: Dict[str, Any] = {}
        elif read.kind == "loaded" and isinstance(read.blob, dict):
            blob = read.blob
        else:
            raise SoulMapUnreadable(f"soul_map {read.kind} at {soul_map_path}: {read.error}")

        now = now_iso()
        rows: Dict[tuple, float] = {}
        if council._raw_has_legacy_contrarian(blob):
            predictions = os.path.join(os.path.dirname(soul_map_path) or "data", "predictions.json")
            expert = council.replay_weights_from_predictions(predictions)
        else:
            snapshot = council._council_weight_snapshot(blob)
            expert = council.normalize_council_weights(snapshot or {})
        for name, value in expert.items():
            rows[("expert", name)] = float(value)

        for horizon, table in council.DEFAULT_SIGNAL_WEIGHTS.items():
            for name, value in table.items():
                rows[(f"signal:{horizon}", name)] = float(value)
        adv = blob.get("adversarial_state")
        adv = adv if isinstance(adv, dict) else {}
        raw_signal = adv.get("signal_weights")
        if isinstance(raw_signal, dict):
            for horizon, table in raw_signal.items():
                if isinstance(table, dict):
                    for name, value in table.items():
                        try:
                            rows[(f"signal:{horizon}", str(name))] = float(value)
                        except (TypeError, ValueError):
                            continue

        impact = council.DEFAULT_IMPACT_STRENGTH
        if adv.get("impact_strength") is not None:
            try:
                impact = float(adv["impact_strength"])
            except (TypeError, ValueError):
                pass
        rows[("impact", "strength")] = impact

        for name, value in judges.normalize_judge_weights(blob.get("judge_weights")).items():
            rows[("judge", name)] = float(value)

        conn.executemany(
            "INSERT OR REPLACE INTO weights(kind, name, value, updated_at) VALUES (?, ?, ?, ?)",
            [(kind, name, value, now) for (kind, name), value in rows.items()],
        )
        slot = council._council_weight_snapshot(blob)
        experts = set(council.DEFAULT_WEIGHTS) | {"contrarian", "darkhorse"}
        known = isinstance(slot, dict) and any(
            str(name).lower().strip() in experts and finite_number(value)
            for name, value in slot.items()
        )
        conn.execute(
            "INSERT OR REPLACE INTO ledger_meta(key, value) VALUES ('weights_known', ?)",
            ("1" if known else "0",),
        )
        for meta_key, source in (
            ("last_weight_update", "last_weight_update"),
            ("last_impact_strength_update", "last_impact_strength_update"),
        ):
            if isinstance(adv.get(source), str):
                conn.execute(
                    "INSERT OR REPLACE INTO ledger_meta(key, value) VALUES (?, ?)", (meta_key, adv[source])
                )
        return read.kind

    return seed


def _seed_pump_blend(cal_path: str) -> Callable[[sqlite3.Connection], str]:
    def seed(conn: sqlite3.Connection) -> str:
        from internal.learning import pump_calibration as pump

        blend = dict(pump._DEFAULTS["blend_weights"])
        state = "missing"
        try:
            with open(cal_path, "r", encoding="utf-8") as handle:
                raw = handle.read()
        except FileNotFoundError:
            raw = None
        except OSError as exc:
            raise LedgerUnreadable(f"pump calibration unreadable at {cal_path}: {exc}") from exc
        if raw is not None and raw.strip():
            try:
                data = json.loads(raw)
            except ValueError as exc:
                raise LedgerUnreadable(f"pump calibration corrupt at {cal_path}: {exc}") from exc
            if not isinstance(data, dict):
                raise LedgerUnreadable(f"pump calibration is not an object at {cal_path}")
            state = "loaded"
            saved = data.get("blend_weights")
            if isinstance(saved, dict):
                for name in blend:
                    if name in saved:
                        try:
                            blend[name] = float(saved[name])
                        except (TypeError, ValueError):
                            pass
        now = now_iso()
        conn.executemany(
            "INSERT OR REPLACE INTO weights(kind, name, value, updated_at) VALUES ('pump_blend', ?, ?, ?)",
            [(name, value, now) for name, value in blend.items()],
        )
        return state

    return seed


@contextmanager
def reader(soul_map_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = soul_map_path or DEFAULT_SOUL_MAP_PATH
    db = ledger_path_for(path)
    _ensure(db, SOUL_MAP_MARKER, _seed_weights_from_soul_map(path), path, path)
    conn = connect(db)
    try:
        yield conn
    except sqlite3.Error as exc:
        raise LedgerUnreadable(f"ledger.db read failed at {db}: {exc}") from exc
    finally:
        conn.close()


@contextmanager
def transaction(soul_map_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = soul_map_path or DEFAULT_SOUL_MAP_PATH
    db = ledger_path_for(path)
    _ensure(db, SOUL_MAP_MARKER, _seed_weights_from_soul_map(path), path, path)
    yield from _write(db)


@contextmanager
def pump_transaction(calibration_path: str) -> Iterator[sqlite3.Connection]:
    db = ledger_path_for(pump_anchor(calibration_path))
    _ensure(
        db, PUMP_MARKER, _seed_pump_blend(calibration_path), calibration_path, pump_anchor(calibration_path)
    )
    yield from _write(db)


@contextmanager
def pump_reader(calibration_path: str) -> Iterator[sqlite3.Connection]:
    db = ledger_path_for(pump_anchor(calibration_path))
    _ensure(
        db, PUMP_MARKER, _seed_pump_blend(calibration_path), calibration_path, pump_anchor(calibration_path)
    )
    conn = connect(db)
    try:
        yield conn
    except sqlite3.Error as exc:
        raise LedgerUnreadable(f"ledger.db read failed at {db}: {exc}") from exc
    finally:
        conn.close()


def _write(db: str) -> Iterator[sqlite3.Connection]:
    conn = connect(db)
    try:
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            raise LedgerUnreadable(f"ledger.db write lock failed at {db}: {exc}") from exc
        try:
            yield conn
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            _rollback(conn)
            raise LedgerUnreadable(f"ledger.db write failed at {db}: {exc}") from exc
        except BaseException:
            _rollback(conn)
            raise
    finally:
        conn.close()


def read_kind(conn: sqlite3.Connection, kind: str) -> Dict[str, float]:
    return {name: value for name, value in conn.execute("SELECT name, value FROM weights WHERE kind=?", (kind,))}


def read_signal_rows(conn: sqlite3.Connection) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for kind, name, value in conn.execute("SELECT kind, name, value FROM weights WHERE kind LIKE 'signal:%'"):
        out.setdefault(kind[len("signal:"):], {})[name] = value
    return out


def current(conn: sqlite3.Connection, kind: str, name: str) -> Optional[float]:
    row = conn.execute("SELECT value FROM weights WHERE kind=? AND name=?", (kind, name)).fetchone()
    return None if row is None else row[0]


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM ledger_meta WHERE key=?", (key,)).fetchone()
    return None if row is None else row[0]


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO ledger_meta(key, value) VALUES (?, ?)", (key, value))


def mark_expert_weights_written(conn: sqlite3.Connection) -> None:
    """An expert write makes the council weights known, as a soul_map write once did."""
    now = now_iso()
    set_meta(conn, "last_weight_update", now)
    set_meta(conn, "weights_known", "1")


def weights_known(soul_map_path: Optional[str] = None) -> bool:
    """True once real council weights were imported or written.

    A soul_map that was missing, or held no usable council weight, seeds defaults. Defaults
    are not knowledge: the scorer gate must not treat them as learned weights.
    """
    with reader(soul_map_path) as conn:
        return get_meta(conn, "weights_known") == "1"


def apply_changes(
    conn: sqlite3.Connection,
    kind: str,
    changes: Dict[str, float],
    *,
    source_id: Optional[str] = None,
    expected: Optional[Dict[str, float]] = None,
) -> tuple[bool, bool]:
    """Write new values inside the caller's transaction, behind the applied key.

    Returns ``(fresh, changed)``: some effect was newly recorded, and some value differs.
    With ``source_id`` a repeat of the same (source, effect) changes nothing and
    ``fresh`` is False. Without one the change gets a fresh key, so it always applies.
    ``expected`` is a compare-and-swap: every changed row must still hold that value,
    else ConcurrentWeightUpdate and the caller's transaction rolls back.
    """
    from internal.council.weights import ConcurrentWeightUpdate

    now = now_iso()
    source = source_id or f"adhoc:{uuid.uuid4().hex}"
    fresh = False
    changed = False
    for name, value in changes.items():
        before = current(conn, kind, name)
        if source_id is None and before == value and not (expected and name in expected):
            continue
        inserted = conn.execute(
            "INSERT OR IGNORE INTO weight_applied(source_id, effect, value_before, value_after, applied_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, f"{kind}:{name}", before, value, now),
        ).rowcount
        if not inserted:
            continue
        fresh = True
        if expected is not None and name in expected:
            swapped = conn.execute(
                "UPDATE weights SET value=?, updated_at=? WHERE kind=? AND name=? AND value=?",
                (value, now, kind, name, expected[name]),
            ).rowcount
            if swapped != 1:
                raise ConcurrentWeightUpdate("weight map changed before replacement")
        else:
            conn.execute(
                "INSERT OR REPLACE INTO weights(kind, name, value, updated_at) VALUES (?, ?, ?, ?)",
                (kind, name, value, now),
            )
        if before != value:
            changed = True
    return fresh, changed
