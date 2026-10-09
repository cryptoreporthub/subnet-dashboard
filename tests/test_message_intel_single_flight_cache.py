"""Single-flight + TTL cache for heavy message_intel loads."""

from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from internal.message_intel import load_guard
from internal.message_intel.rollup import _load_message_rows_uncached
from message_intel.models import Database


@pytest.fixture(autouse=True)
def _clear_intel_load_cache():
    load_guard.clear_message_intel_load_cache()
    yield
    load_guard.clear_message_intel_load_cache()


def test_load_message_rows_single_flight_one_underlying_load(monkeypatch, tmp_path):
    calls = {"n": 0}
    db_path = tmp_path / "mi.db"
    db = Database(str(db_path))

    def _slow(db=None):
        calls["n"] += 1
        time.sleep(0.15)
        return [{"id": 1}]

    monkeypatch.setattr(
        "internal.message_intel.rollup._load_message_rows_uncached",
        _slow,
    )
    from internal.message_intel.rollup import _load_message_rows

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_load_message_rows, db) for _ in range(8)]
        results = [f.result(timeout=5) for f in as_completed(futs)]

    assert calls["n"] == 1
    assert all(r == [{"id": 1}] for r in results)


def test_slow_load_waiters_get_stale_without_stacking(monkeypatch, tmp_path):
    db_path = tmp_path / "mi.db"
    db = Database(str(db_path))
    calls = {"n": 0}
    from internal.message_intel.rollup import _load_message_rows

    monkeypatch.setattr(
        "internal.message_intel.rollup._load_message_rows_uncached",
        lambda db=None: [{"id": 1}],
    )
    assert _load_message_rows(db) == [{"id": 1}]

    def _slow(db=None):
        calls["n"] += 1
        time.sleep(0.25)
        return [{"id": 2}]

    monkeypatch.setattr(
        "internal.message_intel.rollup._load_message_rows_uncached",
        _slow,
    )
    monkeypatch.setattr(load_guard, "DEFAULT_TTL", 0.001)
    monkeypatch.setattr(load_guard, "DEFAULT_WAIT", 0.05)
    time.sleep(0.02)

    leader = threading.Thread(target=_load_message_rows, args=(db,))
    leader.start()
    time.sleep(0.03)
    stale = _load_message_rows(db)
    leader.join(timeout=3)

    assert calls["n"] == 1
    assert stale == [{"id": 1}]


def test_database_connection_closed_after_list_messages(tmp_path):
    db_path = tmp_path / "mi.db"
    db = Database(str(db_path))
    with db._connection() as conn:
        conn.execute(
            "INSERT INTO messages (source, content) VALUES ('telegram', 'x')"
        )
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_netuid_sentiment_rollup_single_flight(monkeypatch, tmp_path):
    db_path = tmp_path / "mi.db"
    db = Database(str(db_path))
    calls = {"n": 0}

    def _slow(limit=40):
        calls["n"] += 1
        time.sleep(0.12)
        return [{"netuid": 1, "mentions": 1}]

    monkeypatch.setattr(db, "_netuid_sentiment_rollup_uncached", _slow)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(db.netuid_sentiment_rollup, limit=40) for _ in range(6)]
        for f in as_completed(futs):
            f.result(timeout=5)
    assert calls["n"] == 1


def test_uncached_load_message_rows_closes_connection(tmp_path):
    db_path = tmp_path / "mi.db"
    db = Database(str(db_path))
    with db._connection() as conn:
        conn.execute(
            "INSERT INTO messages (source, content) VALUES ('telegram', 'hi')"
        )
        conn.commit()
    _load_message_rows_uncached(db)
