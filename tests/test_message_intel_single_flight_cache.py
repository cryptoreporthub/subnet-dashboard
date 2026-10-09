"""Single-flight + TTL cache for heavy message_intel loads."""

from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from internal.message_intel import load_guard
from internal.message_intel.load_guard import LoadTimeout
from internal.message_intel.rollup import _load_message_rows_uncached
from message_intel.models import Database


@pytest.fixture(autouse=True)
def _clear_intel_load_cache():
    load_guard.clear_message_intel_load_cache()
    yield
    load_guard.clear_message_intel_load_cache()


def test_load_message_rows_single_flight_one_underlying_load(monkeypatch, tmp_path):
    calls = {"n": 0}
    db = Database(str(tmp_path / "mi.db"))

    def _slow(db=None):
        calls["n"] += 1
        time.sleep(0.12)
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


def test_hung_leader_waiters_get_immediate_stale(monkeypatch, tmp_path):
    db = Database(str(tmp_path / "mi.db"))
    calls = {"n": 0}
    from internal.message_intel.rollup import _load_message_rows

    monkeypatch.setattr(
        "internal.message_intel.rollup._load_message_rows_uncached",
        lambda db=None: [{"id": 1}],
    )
    assert _load_message_rows(db) == [{"id": 1}]

    def _slow(db=None):
        calls["n"] += 1
        time.sleep(1.0)
        return [{"id": 2}]

    monkeypatch.setattr(
        "internal.message_intel.rollup._load_message_rows_uncached",
        _slow,
    )
    monkeypatch.setattr(load_guard, "DEFAULT_TTL", 0.001)
    time.sleep(0.02)

    leader = threading.Thread(target=_load_message_rows, args=(db,))
    leader.start()
    time.sleep(0.05)
    started = time.perf_counter()
    stale = _load_message_rows(db)
    elapsed = time.perf_counter() - started
    leader.join(timeout=2)

    assert calls["n"] == 1
    assert stale == [{"id": 1}]
    assert elapsed < 0.08


def test_first_time_cold_timeout_raises_loadtimeout(monkeypatch, tmp_path):
    db = Database(str(tmp_path / "mi.db"))
    from internal.message_intel.rollup import _load_message_rows

    def _slow(db=None):
        time.sleep(0.3)
        return [{"id": 99}]

    monkeypatch.setattr(
        "internal.message_intel.rollup._load_message_rows_uncached",
        _slow,
    )
    monkeypatch.setattr(load_guard, "DEFAULT_WAIT", 0.05)

    leader = threading.Thread(target=_load_message_rows, args=(db,))
    leader.start()
    time.sleep(0.02)
    with pytest.raises(LoadTimeout):
        _load_message_rows(db)
    leader.join(timeout=2)


def test_ttl_refresh_invokes_loader_again(monkeypatch, tmp_path):
    db = Database(str(tmp_path / "mi.db"))
    calls = {"n": 0}
    from internal.message_intel.rollup import _load_message_rows

    def _load(db=None):
        calls["n"] += 1
        return [{"id": calls["n"]}]

    monkeypatch.setattr(
        "internal.message_intel.rollup._load_message_rows_uncached",
        _load,
    )
    monkeypatch.setattr(load_guard, "DEFAULT_TTL", 0.02)
    assert _load_message_rows(db) == [{"id": 1}]
    time.sleep(0.03)
    assert _load_message_rows(db) == [{"id": 2}]
    assert calls["n"] == 2


def test_lru_eviction_caps_slot_count(monkeypatch):
    monkeypatch.setattr(load_guard, "MAX_CACHE_SLOTS", 2)
    monkeypatch.setattr(load_guard, "DEFAULT_TTL", 60.0)
    for idx in range(3):
        load_guard.guarded_load(("evict-test", idx), lambda n=idx: {"n": n})
    with load_guard._registry_lock:
        assert len(load_guard._slots) <= 2


def test_large_offset_bypasses_list_messages_cache(monkeypatch, tmp_path):
    db = Database(str(tmp_path / "mi.db"))
    calls = {"n": 0}

    def _uncached(limit, offset):
        calls["n"] += 1
        return []

    monkeypatch.setattr(db, "_list_messages_uncached", _uncached)
    db.list_messages(limit=10, offset=load_guard.MAX_CACHE_OFFSET + 1)
    db.list_messages(limit=10, offset=load_guard.MAX_CACHE_OFFSET + 1)
    assert calls["n"] == 2


def test_database_connection_closed_on_uncached_rows_path(tmp_path):
    db = Database(str(tmp_path / "mi.db"))
    with db._connection() as conn:
        conn.execute(
            "INSERT INTO messages (source, content) VALUES ('telegram', 'hi')"
        )
    _load_message_rows_uncached(db)
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_engine_list_messages_copy_isolation(monkeypatch, tmp_path):
    monkeypatch.setenv("MESSAGE_INTEL_DB", str(tmp_path / "mi.db"))
    from internal.message_intel import engine, store

    store.reset_db_cache()
    impl_calls = {"n": 0}

    def _fake_impl(*args, **kwargs):
        impl_calls["n"] += 1
        return {
            "status": "success",
            "count": 1,
            "messages": [{"id": 1, "content": "a"}],
            "meta": {"ok": True, "total_messages": 1},
            "sources": {},
            "empty": False,
            "filtered_empty": False,
        }

    monkeypatch.setattr(engine, "_list_messages_impl", _fake_impl)
    first = engine.list_messages(limit=8, offset=0)
    first["meta"]["mutated"] = True
    first["messages"][0]["content"] = "changed"
    second = engine.list_messages(limit=8, offset=0)
    assert impl_calls["n"] == 1
    assert "mutated" not in (second.get("meta") or {})
    assert second["messages"][0]["content"] == "a"


def test_engine_list_messages_fresh_listener_on_cache_hit(monkeypatch, tmp_path):
    monkeypatch.setenv("MESSAGE_INTEL_DB", str(tmp_path / "mi.db"))
    from internal.message_intel import engine, store

    store.reset_db_cache()
    statuses = iter([{"live": False}, {"live": True}])

    monkeypatch.setattr(
        engine,
        "_list_messages_impl",
        lambda *a, **k: {
            "status": "success",
            "count": 0,
            "messages": [],
            "meta": {"ok": True, "total_messages": 0},
            "sources": {},
            "empty": True,
            "filtered_empty": False,
        },
    )
    monkeypatch.setattr(
        "internal.message_intel.listener_service.listener_status",
        lambda: next(statuses),
    )
    first = engine.list_messages(limit=5, offset=0)
    second = engine.list_messages(limit=5, offset=0)
    assert first["meta"]["listener"]["live"] is False
    assert second["meta"]["listener"]["live"] is True


def test_netuid_sentiment_rollup_single_flight(monkeypatch, tmp_path):
    db = Database(str(tmp_path / "mi.db"))
    calls = {"n": 0}

    def _slow(limit=40):
        calls["n"] += 1
        time.sleep(0.1)
        return [{"netuid": 1, "mentions": 1}]

    monkeypatch.setattr(db, "_netuid_sentiment_rollup_uncached", _slow)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(db.netuid_sentiment_rollup, limit=40) for _ in range(6)]
        for f in as_completed(futs):
            f.result(timeout=5)
    assert calls["n"] == 1
