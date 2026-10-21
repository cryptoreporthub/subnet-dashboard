from __future__ import annotations

import sqlite3

import pytest

from internal.council import score_snapshots as snaps
from internal.message_intel import rollup
from internal.message_intel.store import get_db, reset_db_cache

JOINED = ("message_analysis", "price_snapshots")


def _indexed_columns(db_path: str, table: str) -> set:
    conn = sqlite3.connect(db_path)
    try:
        cols = set()
        for _, name, *_ in conn.execute(f"PRAGMA index_list({table})").fetchall():
            cols.update(row[2] for row in conn.execute(f"PRAGMA index_info({name})").fetchall())
        return cols
    finally:
        conn.close()


@pytest.fixture
def intel_db(tmp_path, monkeypatch):
    path = str(tmp_path / "message_intel.db")
    monkeypatch.setenv("MESSAGE_INTEL_DB", path)
    reset_db_cache()
    yield path
    reset_db_cache()


@pytest.mark.parametrize("table", JOINED)
def test_conviction_join_columns_are_indexed(intel_db, table):
    get_db()
    assert "message_id" in _indexed_columns(intel_db, table)


@pytest.mark.parametrize("table", JOINED)
def test_legacy_database_gains_the_join_indexes_on_open(intel_db, table):
    get_db()
    conn = sqlite3.connect(intel_db)
    for _, name, *_ in conn.execute(f"PRAGMA index_list({table})").fetchall():
        if not name.startswith("sqlite_autoindex"):
            conn.execute(f"DROP INDEX {name}")
    conn.commit()
    conn.close()
    assert "message_id" not in _indexed_columns(intel_db, table)
    reset_db_cache()
    get_db()
    assert "message_id" in _indexed_columns(intel_db, table)


def test_conviction_query_searches_its_joins_instead_of_scanning(intel_db, monkeypatch):
    seen = []
    original = sqlite3.connect

    def _tracing_connect(*args, **kwargs):
        conn = original(*args, **kwargs)
        conn.set_trace_callback(seen.append)
        return conn

    db = get_db()
    monkeypatch.setattr("message_intel.models.sqlite3.connect", _tracing_connect)
    rollup._query_conviction_rows(db)
    select = next(s for s in seen if "FROM messages m" in s)
    conn = original(intel_db)
    try:
        plan = [row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + select).fetchall()]
    finally:
        conn.close()
    joined = [d for d in plan if " a " in f" {d} " or " ps " in f" {d} "]
    assert joined and all(d.startswith("SEARCH") for d in joined), plan


def _score_all_stubbed(monkeypatch, count):
    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_day", lambda sn, ctx: {"total_score": 1.0})
    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_hour", lambda sn, ctx: {"total_score": 1.0})
    monkeypatch.setattr("internal.subnets.tradable.tradable_subnets", lambda rows: rows)
    ticks = []
    snaps.build_full_universe_snapshot(
        [{"netuid": n, "price": 1} for n in range(1, count + 1)],
        {},
        score_hour=False,
        progress_cb=lambda done, total: ticks.append((done, total)),
    )
    return ticks


def test_fast_build_writes_no_progress_heartbeat(monkeypatch):
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_PROGRESS_MIN_SECONDS", 3600, raising=False)
    assert _score_all_stubbed(monkeypatch, 60) == []


def test_progress_heartbeat_fires_once_the_interval_has_passed(monkeypatch):
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_PROGRESS_MIN_SECONDS", 0, raising=False)
    ticks = _score_all_stubbed(monkeypatch, 60)
    assert ticks and ticks[-1] == (60, 60)
