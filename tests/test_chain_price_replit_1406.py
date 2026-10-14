"""Regressions for Replit's four #1406 MODIFY items (membership, fallback, cooldown, vacuum)."""

from __future__ import annotations

import copy
import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

from internal.chain_price import db as price_db
from internal.chain_price.membership import get_member_netuids
from internal.chain_price.reader import ChainReader
from internal.chain_price.rpc import rpc_call
from internal.chain_rpc_errors import ChainRpcError

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "chain" / "bm_9060887.json"
PINNED_HASH = "0x9df0d42a0637e3e4628ccef850f8792b28cf0c7a1695bae73e6a9c6de989fb8c"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _storage_params(data: dict):
    key = next(k for k in data if k.startswith("state_queryStorageAt|"))
    keys, at_hash = json.loads(key.split("|", 1)[1])
    return keys, at_hash


class _Replay:
    """Serves the fixture; ``mutate`` rewrites a response before the reader sees it."""

    def __init__(self, data: dict, mutate=None):
        self._data = data
        self._mutate = mutate

    def _respond(self, method, params=None):
        key = f"{method}|{json.dumps(params or [])}"
        value = copy.deepcopy(self._data[key])
        if self._mutate is not None:
            value = self._mutate(method, value)
        return value

    def _call_typed(self, method, params=None):
        return self._respond(method, params)

    def _call(self, method, params=None):
        return self._respond(method, params)

    def query_storage_at(self, keys, at_hash):
        return self._respond("state_queryStorageAt", [keys, at_hash])


def _changes(mutator):
    """Mutate the ``changes`` list of the state_queryStorageAt response only."""

    def _mutate(method, value):
        if method == "state_queryStorageAt":
            mutator(value[0]["changes"])
        return value

    return _mutate


def _report_block(block_hash):
    def _mutate(method, value):
        if method == "state_queryStorageAt":
            value[0]["block"] = block_hash
        return value

    return _mutate


def _membership(provider):
    def call(method, params):
        return rpc_call(provider, method, params)

    return get_member_netuids(call, PINNED_HASH)


# Item 1: every enumerated netuid needs a decodable bool. Missing or malformed is invalid, not false.


def test_membership_baseline_fixture_is_ok():
    netuids, outcome = _membership(_Replay(_load_fixture()))
    assert outcome == "ok"
    assert 64 in netuids


def test_membership_missing_enumerated_key_fails_closed():
    data = _load_fixture()

    def _drop_first(changes):
        changes.pop(0)

    assert _membership(_Replay(data, mutate=_changes(_drop_first))) == ([], "invalid")


def test_membership_non_bool_value_fails_closed():
    data = _load_fixture()

    def _bad_value(changes):
        changes[0][1] = "0x02"

    assert _membership(_Replay(data, mutate=_changes(_bad_value))) == ([], "invalid")


def test_membership_empty_changes_fails_closed():
    data = _load_fixture()

    def _clear(changes):
        changes.clear()

    assert _membership(_Replay(data, mutate=_changes(_clear))) == ([], "invalid")


# Item 2: an invalid answer from the primary must reach the fallback. The hash echo still gates it.


def test_primary_echo_mismatch_falls_back_to_good_provider():
    data = _load_fixture()
    keys, at_hash = _storage_params(data)
    reader = ChainReader(
        [
            ("finney", _Replay(data, mutate=_report_block("0xdeadbeef"))),
            ("blockmachine", _Replay(data)),
        ]
    )
    result, outcome = reader.call("state_queryStorageAt", [keys, at_hash])
    assert outcome == "ok"
    assert result[0]["block"] == at_hash
    assert reader.provider_served == "blockmachine"


def test_bad_fallback_also_mismatched_fails_closed():
    data = _load_fixture()
    keys, at_hash = _storage_params(data)
    bad = _Replay(data, mutate=_report_block("0xdeadbeef"))
    reader = ChainReader([("finney", bad), ("blockmachine", copy.copy(bad))])
    result, outcome = reader.call("state_queryStorageAt", [keys, at_hash])
    assert result is None
    assert outcome == "invalid"
    assert reader.provider_served is None


# Item 3: the rate-limit ladder resets once a provider answers successfully.


class _Scripted:
    """Each call pops the next item: an exception is raised, anything else is returned."""

    def __init__(self, script):
        self._script = list(script)

    def _next(self):
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def _call_typed(self, method, params=None):
        return self._next()

    def _call(self, method, params=None):
        return self._next()


def test_cooldown_resets_after_success():
    clock = [1000.0]
    finney = _Scripted(
        [
            ChainRpcError("rate_limited", "429"),  # 1000s: cooldown 600s, until 1600
            "0x01",  # 1700s: after expiry, success clears the ladder
            ChainRpcError("rate_limited", "429"),  # 1700s: next limit starts at 600s again
        ]
    )
    reader = ChainReader([("finney", finney)])
    with patch("internal.chain_price.reader.time.time", side_effect=lambda: clock[0]):
        assert reader.call("chain_getFinalizedHead", []) == (None, "rate_limited")
        assert reader._cooldown_until["finney"] == 1600.0
        clock[0] = 1700.0
        assert reader.call("chain_getFinalizedHead", []) == ("0x01", "ok")
        assert reader.call("chain_getFinalizedHead", []) == (None, "rate_limited")
    assert reader._cooldown_seconds["finney"] == 600.0
    assert reader._cooldown_until["finney"] == 2300.0


def test_cooldown_still_escalates_without_success():
    clock = [1000.0]
    finney = _Scripted([ChainRpcError("rate_limited", "429")] * 2)
    reader = ChainReader([("finney", finney)])
    with patch("internal.chain_price.reader.time.time", side_effect=lambda: clock[0]):
        reader.call("chain_getFinalizedHead", [])
        clock[0] = 1700.0
        reader.call("chain_getFinalizedHead", [])
    assert reader._cooldown_seconds["finney"] == 1200.0


# Item 4: incremental vacuum must actually free pages, bounded per call.


def _bloat(path, rows=5000):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE junk (b TEXT)")
    conn.executemany("INSERT INTO junk VALUES (?)", [("x" * 1000,) for _ in range(rows)])
    conn.commit()
    conn.execute("DELETE FROM junk")
    conn.commit()
    return conn


def test_auto_vacuum_is_incremental_on_fresh_file(tmp_path):
    db = tmp_path / "fresh.db"
    price_db.ensure_schema(str(db))
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
    finally:
        conn.close()


def test_incremental_vacuum_reclaims_at_most_requested_pages(tmp_path):
    db = tmp_path / "bloated.db"
    price_db.ensure_schema(str(db))
    conn = _bloat(str(db))
    try:
        before = conn.execute("PRAGMA freelist_count").fetchone()[0]
        assert before >= 10
        size_before = os.path.getsize(db)

        reclaimed = price_db.incremental_vacuum(conn, 5)
        assert reclaimed == 5
        assert conn.execute("PRAGMA freelist_count").fetchone()[0] == before - 5
        # WAL mode: the main file only shrinks once the WAL is checkpointed.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        assert os.path.getsize(db) < size_before

        reclaimed_rest = price_db.incremental_vacuum(conn, 10_000)
        assert reclaimed_rest == before - 5
        assert conn.execute("PRAGMA freelist_count").fetchone()[0] == 0
    finally:
        conn.close()


def test_incremental_vacuum_is_noop_without_auto_vacuum(tmp_path):
    db = tmp_path / "plain.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute("CREATE TABLE t (v INTEGER)")
        assert price_db.incremental_vacuum(conn, 100) == 0
    finally:
        conn.close()


def test_hourly_prune_calls_bounded_vacuum(tmp_path):
    db = str(tmp_path / "prune.db")
    price_db.ensure_schema(db)
    with patch.object(price_db, "VACUUM_PAGES_PER_RUN", 7), patch.object(
        price_db, "incremental_vacuum", wraps=price_db.incremental_vacuum
    ) as vac:
        price_db.run_hourly_prune_job(path=db)
    vac.assert_called_once()
    assert vac.call_args.args[1] == 7
