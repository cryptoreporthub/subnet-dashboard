"""Regression tests for Replit's #1395 Step 2 review findings (1-3) on PR #1406."""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from internal.chain_price import config as cfg
from internal.chain_price import db as price_db
from internal.chain_price.reader import ChainReader
from internal.chain_price.sampler import run_forward_sample, sample_sn64_from_block
from internal.chain_rpc_errors import ChainRpcError

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "chain" / "bm_9060887.json"
PINNED_HASH = "0x9df0d42a0637e3e4628ccef850f8792b28cf0c7a1695bae73e6a9c6de989fb8c"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


class _ReplayProvider:
    """Serves the fixture; can fail every call, or only the named methods."""

    def __init__(self, data: dict, *, down: bool = False, fail_methods=(), mutate=None):
        self._data = data
        self._down = down
        self._fail = set(fail_methods)
        self._mutate = mutate

    def _respond(self, method, params=None):
        if self._down or method in self._fail:
            raise ChainRpcError("rpc_error", f"{method} unavailable")
        key = f"{method}|{json.dumps(params or [])}"
        if key not in self._data:
            raise RuntimeError(f"missing fixture for {key}")
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


def _reader(*providers):
    return ChainReader(list(providers))


def _run(reader, db_path):
    with patch.object(cfg, "forward_record_enabled", return_value=True):
        return run_forward_sample(reader, db_path=str(db_path), write=True)


def _rows(db_path, sql):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# Finding 2 (provenance): the stored provider must be the one that served the reserves.


def test_provider_recorded_when_primary_down_is_fallback(tmp_path):
    data = _load_fixture()
    db = tmp_path / "chain_prices.db"
    reader = _reader(
        ("finney", _ReplayProvider(data, down=True)),
        ("blockmachine", _ReplayProvider(data)),
    )
    result = _run(reader, db)
    assert result["outcome"] == "ok"
    assert _rows(db, "SELECT DISTINCT provider FROM chain_blocks") == [("blockmachine",)]
    assert _rows(db, "SELECT DISTINCT provider FROM chain_price_samples") == [("blockmachine",)]


def test_spot_only_failover_keeps_storage_provider(tmp_path):
    # Finney serves the reserve batch but fails the spot read; Blockmachine answers the spot.
    data = _load_fixture()
    db = tmp_path / "chain_prices.db"
    reader = _reader(
        ("finney", _ReplayProvider(data, fail_methods={"swap_currentAlphaPrice"})),
        ("blockmachine", _ReplayProvider(data)),
    )
    result = _run(reader, db)
    assert result["outcome"] == "ok"
    assert _rows(db, "SELECT DISTINCT provider FROM chain_blocks") == [("finney",)]
    assert _rows(db, "SELECT DISTINCT provider FROM chain_price_samples") == [("finney",)]


def test_both_providers_down_writes_nothing(tmp_path):
    data = _load_fixture()
    db = tmp_path / "chain_prices.db"
    reader = _reader(
        ("finney", _ReplayProvider(data, down=True)),
        ("blockmachine", _ReplayProvider(data, down=True)),
    )
    result = _run(reader, db)
    assert result["outcome"] != "ok"
    assert _rows(db, "SELECT COUNT(*) FROM chain_blocks") == [(0,)]
    assert _rows(db, "SELECT COUNT(*) FROM chain_price_samples") == [(0,)]


# Finding 1 (block identity): a storage read that reports another block must never persist.


def _report_block(block_hash_value):
    def _mutate(method, value):
        if method == "state_queryStorageAt":
            value[0]["block"] = block_hash_value
        return value

    return _mutate


def test_returned_block_mismatch_writes_neither_blocks_nor_samples(tmp_path):
    data = _load_fixture()
    db = tmp_path / "chain_prices.db"
    reader = _reader(
        ("blockmachine", _ReplayProvider(data, mutate=_report_block("0xdeadbeef"))),
    )
    result = _run(reader, db)
    assert result["outcome"] == "invalid"
    assert _rows(db, "SELECT COUNT(*) FROM chain_blocks") == [(0,)]
    assert _rows(db, "SELECT COUNT(*) FROM chain_price_samples") == [(0,)]


def test_storage_read_without_block_field_fails_closed(tmp_path):
    data = _load_fixture()
    db = tmp_path / "chain_prices.db"

    def _drop_block(method, value):
        if method == "state_queryStorageAt":
            value[0].pop("block", None)
        return value

    reader = _reader(("blockmachine", _ReplayProvider(data, mutate=_drop_block)))
    result = _run(reader, db)
    assert result["outcome"] == "invalid"
    assert _rows(db, "SELECT COUNT(*) FROM chain_blocks") == [(0,)]
    assert _rows(db, "SELECT COUNT(*) FROM chain_price_samples") == [(0,)]


def test_offline_sn64_helper_rejects_block_mismatch():
    data = _load_fixture()
    provider = _ReplayProvider(data, mutate=_report_block("0xdeadbeef"))
    with pytest.raises(AssertionError, match="networks added failed: invalid"):
        sample_sn64_from_block(provider, PINNED_HASH)


# Finding 3 (identity): the Bittensor status row must not present a Blockmachine probe as Finney
# without naming the transport, and must follow a configured Finney endpoint when one is set.


def _status_row(rpc_url: str, network: str = "finney") -> dict:
    from internal.integrations import status as st

    st.clear_status_cache()
    with patch.object(st, "_BITTENSOR_RPC", rpc_url), patch.object(
        st, "_BITTENSOR_NETWORK", network
    ), patch.object(st, "_rpc_chain_healthy", return_value=(True, "chain RPC ok")), patch.object(
        st, "_http_probe", return_value=(True, 200, "ok")
    ):
        payload = st.build_integrations_status(force=True)
    return next(r for r in payload["integrations"] if r["slug"] == "bittensor")


def test_status_default_config_names_blockmachine_transport():
    row = _status_row("https://rpc.blockmachine.io")
    assert "via Blockmachine" in row["detail"]
    assert "Finney mainnet" in row["detail"]
    assert row["rpc_transport"] == "via Blockmachine"


def test_status_finney_endpoint_is_not_labelled_blockmachine():
    row = _status_row("https://entrypoint-finney.opentensor.ai")
    assert "via Finney RPC" in row["detail"]
    assert "Blockmachine" not in row["detail"]
    assert row["rpc_transport"] == "via Finney RPC"


# Review item (db): auto_vacuum must actually apply, on fresh and pre-existing files.


def _auto_vacuum(path) -> int:
    return _rows(path, "PRAGMA auto_vacuum")[0][0]


def test_fresh_db_gets_incremental_auto_vacuum(tmp_path):
    db = tmp_path / "fresh.db"
    price_db.ensure_schema(str(db))
    assert _auto_vacuum(db) == 2


def test_existing_db_is_converted_to_incremental_auto_vacuum(tmp_path):
    db = tmp_path / "v1.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE keep (v INTEGER)")
    conn.execute("INSERT INTO keep VALUES (7)")
    conn.commit()
    conn.close()
    assert _auto_vacuum(db) == 0
    price_db.ensure_schema(str(db))
    assert _auto_vacuum(db) == 2
    assert _rows(db, "SELECT v FROM keep") == [(7,)]
    price_db.ensure_schema(str(db))  # idempotent: second call must not fail or reset data
    assert _rows(db, "SELECT v FROM keep") == [(7,)]


def test_first_rate_limit_cooldown_is_sixty_seconds():
    from internal.chain_client import ChainClient, _RL_LOCK, _RL_STEP, _RL_UNTIL

    client = ChainClient("https://finney.example", init_volume_db=False)
    reader = ChainReader([("finney", client)])
    with _RL_LOCK:
        _RL_UNTIL.clear()
        _RL_STEP.clear()
    reader._mark_rate_limited("finney", client)
    assert _RL_STEP[client.endpoint] == 120.0
    reader._mark_rate_limited("finney", client)
    assert _RL_STEP[client.endpoint] == 240.0


# Motivating live case: Finney answers swap_currentAlphaPrice at a pinned block with
# code 1 "State already discarded"; Blockmachine serves it. The reader must fall back.

FINNEY_DISCARDED_BODY = {
    "code": 1,
    "message": "Unable to get current alpha price: UnknownBlock(\"State already discarded for "
    "0x9df0d42a0637e3e4628ccef850f8792b28cf0c7a1695bae73e6a9c6de989fb8c\")",
}


def test_finney_discarded_state_classifies_as_archive_miss_and_falls_back():
    from internal.chain_client import ChainClient
    from internal.chain_price.rpc import rpc_call

    data = _load_fixture()

    class _Resp:
        def __init__(self, body, status=200):
            self._body = body
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

        def json(self):
            return self._body

    def _post(url, json=None, headers=None, timeout=None):
        method, params = json["method"], json["params"]
        if "finney" in url and method == "swap_currentAlphaPrice":
            return _Resp({"jsonrpc": "2.0", "error": FINNEY_DISCARDED_BODY, "id": 1})
        key = f"{method}|{__import__('json').dumps(params or [])}"
        return _Resp({"jsonrpc": "2.0", "result": data[key], "id": 1})

    finney = ChainClient(endpoint="https://entrypoint-finney.opentensor.ai", init_volume_db=False)
    blockmachine = ChainClient(endpoint="https://rpc.blockmachine.io", init_volume_db=False)
    with patch("internal.chain_client.requests.post", side_effect=_post):
        _, direct = rpc_call(finney, "swap_currentAlphaPrice", [64, PINNED_HASH])
        assert direct == "archive_miss"
        reader = ChainReader([("finney", finney), ("blockmachine", blockmachine)])
        value, outcome = reader.call("swap_currentAlphaPrice", [64, PINNED_HASH])
    assert outcome == "ok"
    assert value == 69438359
    assert reader.provider_served == "blockmachine"


# Step 0 (main e97facc) schema, copied verbatim: the pre-state a real pre-change file has.
STEP0_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chain_blocks (
    provider TEXT NOT NULL, block INTEGER NOT NULL, block_hash TEXT NOT NULL,
    ts_ms INTEGER NOT NULL, bucket_ts INTEGER NOT NULL, kind TEXT NOT NULL,
    n_subnets INTEGER NOT NULL, recorded_at TEXT NOT NULL,
    PRIMARY KEY (provider, block)
);
CREATE TABLE IF NOT EXISTS chain_price_samples (
    netuid INTEGER NOT NULL, block INTEGER NOT NULL, provider TEXT NOT NULL,
    ts_ms INTEGER NOT NULL, registered_at INTEGER NOT NULL,
    tao_reserve_raw INTEGER NOT NULL, alpha_reserve_raw INTEGER NOT NULL,
    price_tao REAL NOT NULL, spot_price_tao REAL, unit TEXT NOT NULL DEFAULT 'tao',
    quality TEXT NOT NULL, schema_version INTEGER NOT NULL,
    PRIMARY KEY (netuid, block, provider)
);
"""


def test_step0_wal_file_is_converted_migrated_and_keeps_rows(tmp_path):
    from internal.store.db import db_conn

    db = tmp_path / "step0.db"
    with db_conn(str(db)) as conn:  # the path Step 0 used: WAL, shared connection
        conn.executescript(STEP0_SCHEMA_SQL)
        conn.execute(
            "INSERT INTO chain_price_samples VALUES (64, 9060887, 'blockmachine', 1789328964000,"
            " 4531295, 200327976535187, 2884975669612746, 0.0694, NULL, 'tao', 'chain_sampled', 1)"
        )
        conn.commit()
    price_db.ensure_schema(str(db))
    assert _auto_vacuum(db) == 2
    cols = {r[1] for r in _rows(db, "PRAGMA table_info(chain_price_samples)")}
    assert {"block_hash", "series_key"} <= cols  # v2 migration ran
    assert _rows(db, "SELECT netuid, block, price_tao FROM chain_price_samples") == [
        (64, 9060887, 0.0694)
    ]
    assert _rows(db, "PRAGMA journal_mode")[0][0].lower() == "wal"


def test_vacuum_failure_is_logged_and_schema_still_applies(tmp_path, caplog):
    from contextlib import contextmanager

    from internal.store.db import db_conn as real_db_conn

    class _VacuumFails:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, *args):
            if sql.strip().upper() == "VACUUM":
                raise sqlite3.OperationalError("database is locked")
            return self._conn.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    @contextmanager
    def _wrapped(path=None):
        with real_db_conn(path) as conn:
            yield _VacuumFails(conn)

    db = tmp_path / "vacuum-blocked.db"
    with real_db_conn(str(db)) as conn:
        conn.executescript(STEP0_SCHEMA_SQL)
        conn.commit()
    with patch.object(price_db, "db_conn", _wrapped), caplog.at_level("WARNING"):
        price_db.ensure_schema(str(db))
    assert any("VACUUM skipped" in r.message for r in caplog.records)
    assert _rows(db, "SELECT COUNT(*) FROM chain_blocks") == [(0,)]


# Finding 2, end to end: env → default ChainReader() → run_forward_sample → stored provider.


class _HttpResp:
    def __init__(self, body):
        self._body = body
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


def test_env_providers_fall_back_end_to_end_and_store_served_provider(tmp_path, monkeypatch):
    import requests

    data = _load_fixture()
    monkeypatch.setenv("FINNEY_RPC_URL", "https://finney.test")
    monkeypatch.setenv("BLOCKMACHINE_RPC_URL", "https://bm.test")

    def _post(url, json=None, headers=None, timeout=None):
        if "finney.test" in url:
            raise requests.ConnectionError("finney unreachable")
        key = f"{json['method']}|{__import__('json').dumps(json['params'] or [])}"
        return _HttpResp({"jsonrpc": "2.0", "result": data[key], "id": 1})

    db = tmp_path / "e2e.db"
    with patch("internal.chain_client.requests.post", side_effect=_post), patch(
        "internal.chain_client.time.sleep"
    ), patch.object(cfg, "forward_record_enabled", return_value=True):
        reader = ChainReader()  # default constructor: providers come from the environment
        result = run_forward_sample(reader, db_path=str(db), write=True)
    assert result["outcome"] == "ok"
    assert _rows(db, "SELECT DISTINCT provider FROM chain_blocks") == [("blockmachine",)]
    assert _rows(db, "SELECT DISTINCT provider FROM chain_price_samples") == [("blockmachine",)]


@pytest.mark.parametrize(
    "finney,blockmachine,expected",
    [
        (None, None, [("https://rpc.blockmachine.io", "blockmachine")]),
        ("https://finney.test/", None, [("https://finney.test", "finney"), ("https://rpc.blockmachine.io", "blockmachine")]),
        ("https://same.test", "https://same.test", [("https://same.test", "finney")]),
    ],
)
def test_provider_endpoints_from_environment(monkeypatch, finney, blockmachine, expected):
    monkeypatch.delenv("FINNEY_RPC_URL", raising=False)
    monkeypatch.delenv("BLOCKMACHINE_RPC_URL", raising=False)
    if finney:
        monkeypatch.setenv("FINNEY_RPC_URL", finney)
    if blockmachine:
        monkeypatch.setenv("BLOCKMACHINE_RPC_URL", blockmachine)
    assert cfg.rpc_provider_endpoints() == expected


# Resolver: the timestamp read must go through the reader's fallback.


def test_resolve_block_at_falls_back_when_primary_fails(monkeypatch):
    from internal.chain_price.block_resolve import clear_block_cache, resolve_block_at
    from internal.chain_price.storage_keys import timestamp_now_key_hex

    clear_block_cache()
    data = _load_fixture()
    key = timestamp_now_key_hex()
    ts_raw = next(
        row[1]
        for k, v in data.items()
        if k.startswith("state_queryStorageAt|")
        for row in (v[0].get("changes") or [])
        if row[0] == key
    )
    ts_ms = 1789328964000
    head = {
        "chain_getFinalizedHead": PINNED_HASH,
        "chain_getHeader": {"number": hex(9060887)},
        "chain_getBlockHash": PINNED_HASH,
    }

    class _Served:
        def __init__(self, down=False):
            self.down = down

        def _respond(self, method, params=None):
            if self.down:
                raise ChainRpcError("rpc_error", "finney down")
            if method == "state_queryStorageAt":
                return [{"block": PINNED_HASH, "changes": [[key, ts_raw]]}]
            return head[method]

        def _call_typed(self, method, params=None):
            return self._respond(method, params)

        def _call(self, method, params=None):
            return self._respond(method, params)

        def query_storage_at(self, keys, at_hash):
            return self._respond("state_queryStorageAt", [keys, at_hash])

    reader = ChainReader([("finney", _Served(down=True)), ("blockmachine", _Served())])
    block, block_hash, outcome = resolve_block_at(reader, ts_ms)
    assert (block, block_hash, outcome) == (9060887, PINNED_HASH, "ok")
    assert reader.provider_served == "blockmachine"
    clear_block_cache()
    both_down = ChainReader([("finney", _Served(down=True)), ("blockmachine", _Served(down=True))])
    assert resolve_block_at(both_down, ts_ms)[2] != "ok"
    clear_block_cache()


# Upgrade path: a Step 0 file is migrated, then the next tick writes and prunes it without error.


def test_migrated_step0_file_accepts_a_tick_and_prune(tmp_path):
    from internal.chain_price.bars import get_chain_bar
    from internal.store.db import db_conn

    data = _load_fixture()
    db = tmp_path / "upgrade.db"
    with db_conn(str(db)) as conn:
        conn.executescript(STEP0_SCHEMA_SQL)
        conn.execute(
            "INSERT INTO chain_price_samples VALUES (64, 9000000, 'blockmachine', 1789000000000,"
            " 4531295, 1, 1, 0.5, NULL, 'tao', 'chain_sampled', 1)"
        )
        conn.commit()
    price_db.ensure_schema(str(db))
    reader = ChainReader([("blockmachine", _ReplayProvider(data))])
    with patch.object(cfg, "forward_record_enabled", return_value=True):
        result = run_forward_sample(reader, db_path=str(db), write=True)
    assert result["outcome"] == "ok"
    price_db.prune_old_rows(path=str(db))
    assert _rows(db, "SELECT COUNT(*) FROM chain_price_samples WHERE block = 9000000") == [(1,)]
    # The v1 row has no series_key, so the v2 selector must not pick it up.
    assert get_chain_bar(64, 4531295, 1789000000000, path=str(db)) is None


def test_resolve_block_at_rejects_unechoed_timestamp_read():
    # The timestamp read is a pinned storage read: a response that does not echo the probed block,
    # or omits the block, must fail closed rather than resolve to an unverified block.
    from internal.chain_price.block_resolve import clear_block_cache, resolve_block_at
    from internal.chain_price.storage_keys import timestamp_now_key_hex

    key = timestamp_now_key_hex()
    ts_ms = 1789328964000
    ts_hex = "0x" + ts_ms.to_bytes(8, "little").hex()
    entries = {
        "mismatched": {"block": "0x" + "de" * 32, "changes": [[key, ts_hex]]},
        "missing": {"changes": [[key, ts_hex]]},
    }

    class _Unechoed:
        def __init__(self, entry):
            self.entry = entry

        def call(self, method, params=None):
            if method == "chain_getFinalizedHead":
                return PINNED_HASH, "ok"
            if method == "chain_getHeader":
                return {"number": hex(9060887)}, "ok"
            if method == "chain_getBlockHash":
                return PINNED_HASH, "ok"
            if method == "state_queryStorageAt":
                return [self.entry], "ok"
            raise AssertionError(f"unexpected method {method}")

        def call_fn(self):
            return self.call

    for name, entry in entries.items():
        clear_block_cache()
        assert resolve_block_at(_Unechoed(entry), ts_ms) == (None, None, "invalid"), name
    clear_block_cache()
