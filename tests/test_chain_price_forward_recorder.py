"""Forward chain price recorder (#1395 Step 0)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from internal.chain_client import ChainClient
from internal.chain_price import config as cfg
from internal.chain_price import db as price_db
from internal.chain_price.sampler import (
    _crosscheck_netuids,
    run_forward_sample,
    sample_sn64_from_block,
)
from internal.chain_price.storage_keys import (
    netuid_from_networks_added_key,
    networks_added_prefix_hex,
    reserve_query_keys,
)
from internal.message_intel.stake_alert import twox128

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "chain" / "bm_9060887.json"
PINNED_HASH = "0x9df0d42a0637e3e4628ccef850f8792b28cf0c7a1695bae73e6a9c6de989fb8c"


def _fixture_key(method: str, params: list) -> str:
    return f"{method}|{json.dumps(params)}"


@pytest.fixture
def fixture_replay():
    data = json.loads(FIXTURE_PATH.read_text())

    def _call(self, method, params=None):
        params = params or []
        key = _fixture_key(method, params)
        if key not in data:
            raise RuntimeError(f"missing fixture for {key}")
        return data[key]

    client = ChainClient.__new__(ChainClient)
    client._call = lambda method, params=None: _call(client, method, params)  # type: ignore[method-assign]
    return client, data


def test_fixture_sn64_values(fixture_replay):
    client, _ = fixture_replay
    row = sample_sn64_from_block(client, PINNED_HASH)
    assert row["tao_reserve_raw"] == 200327976535187
    assert row["alpha_reserve_raw"] == 2884975669612746
    assert abs(row["price_tao"] - 0.06943835909786972) < 1e-12
    assert row["spot_raw"] == 69438359
    assert row["registered_at"] == 4531295
    assert row["ts_ms"] == 1789328964000
    assert row["unit"] == "tao"
    assert row["quality"] == "chain_sampled"


def test_forward_sample_writes_once(fixture_replay, tmp_path):
    client, data = fixture_replay
    db_path = str(tmp_path / "chain_prices.db")
    with patch.object(cfg, "forward_record_enabled", return_value=True):
        first = run_forward_sample(client, db_path=db_path, write=True)
        second = run_forward_sample(client, db_path=db_path, write=True)
    assert first["outcome"] == "ok"
    assert second["outcome"] == "ok"
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM chain_price_samples").fetchone()[0]
    block_count = conn.execute("SELECT COUNT(*) FROM chain_blocks").fetchone()[0]
    conn.close()
    assert block_count == 1
    assert count == first["samples_written"]
    assert second["samples_written"] == 0


def test_non_ok_outcome_does_not_write(tmp_path):
    db_path = str(tmp_path / "chain_prices.db")

    class _BrokenClient:
        def _call(self, method, params=None):
            raise RuntimeError("HTTP 429 Too Many Requests")

    with patch.object(cfg, "forward_record_enabled", return_value=True):
        result = run_forward_sample(_BrokenClient(), db_path=db_path, write=True)
    assert result["outcome"] == "rate_limited"
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM chain_price_samples").fetchone()[0] == 0
    conn.close()


def test_storage_prefix_matches_fixture():
    mod = twox128(b"SubtensorModule")
    assert mod.hex() == "658faa385070e074c85bf6b568cf0555"
    assert (mod + twox128(b"SubnetTAO")).hex().endswith("7a57dce016211512d1700561066b85a3")


def test_spot_crosscheck_failure_still_persists(fixture_replay, tmp_path):
    client, data = fixture_replay
    db_path = str(tmp_path / "chain_prices.db")
    netuids = sorted(
        {
            netuid_from_networks_added_key(k)
            for k in data[
                _fixture_key(
                    "state_getKeysPaged",
                    [networks_added_prefix_hex(), 200, None, PINNED_HASH],
                )
            ]
            if netuid_from_networks_added_key(k)
        }
    )
    header = data[_fixture_key("chain_getHeader", [PINNED_HASH])]
    block = int(header["number"], 16)
    fail_netuid = _crosscheck_netuids(netuids, block)[0]

    real_call = client._call

    def _call(method, params=None):
        params = params or []
        if method == "swap_currentAlphaPrice" and params and params[0] == fail_netuid:
            raise RuntimeError("spot RPC down")
        return real_call(method, params)

    client._call = _call  # type: ignore[method-assign]

    with patch.object(cfg, "forward_record_enabled", return_value=True):
        result = run_forward_sample(client, db_path=db_path, write=True)
    assert result["outcome"] == "ok"
    assert result.get("spot_crosscheck_failures") == 1
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT spot_price_tao FROM chain_price_samples WHERE netuid = ?",
        (fail_netuid,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] is None


def test_prune_enforces_retention_and_row_cap(tmp_path):
    db_path = str(tmp_path / "chain_prices.db")
    price_db.ensure_schema(db_path)
    now_ms = int(time.time() * 1000)
    old_ms = now_ms - (cfg.RETENTION_DAYS + 1) * 86400 * 1000
    rows = [
        {
            "netuid": 1,
            "block": i,
            "provider": "test",
            "ts_ms": old_ms if i == 0 else now_ms,
            "registered_at": 1,
            "tao_reserve_raw": 1,
            "alpha_reserve_raw": 1,
            "price_tao": 1.0,
            "spot_price_tao": None,
            "unit": "tao",
            "quality": "chain_sampled",
            "schema_version": cfg.SCHEMA_VERSION,
        }
        for i in range(3)
    ]
    assert price_db.insert_sample_rows(rows, path=db_path) == 3
    stats = price_db.prune_old_rows(path=db_path)
    assert stats["deleted_samples"] >= 1
    conn = sqlite3.connect(db_path)
    remaining = conn.execute("SELECT COUNT(*) FROM chain_price_samples").fetchone()[0]
    conn.close()
    assert remaining == 2

    with patch.object(price_db, "ROW_CAP", 2):
        extra = [
            {
                "netuid": 2,
                "block": 100 + i,
                "provider": "test",
                "ts_ms": now_ms + i,
                "registered_at": 1,
                "tao_reserve_raw": 1,
                "alpha_reserve_raw": 1,
                "price_tao": 1.0,
                "spot_price_tao": None,
                "unit": "tao",
                "quality": "chain_sampled",
                "schema_version": cfg.SCHEMA_VERSION,
            }
            for i in range(3)
        ]
        price_db.insert_sample_rows(extra, path=db_path)
        cap_stats = price_db.prune_old_rows(path=db_path)
        assert cap_stats["deleted_samples"] >= 1
        conn = sqlite3.connect(db_path)
        capped = conn.execute("SELECT COUNT(*) FROM chain_price_samples").fetchone()[0]
        conn.close()
        assert capped <= 2


def test_fixture_has_full_storage_batch(fixture_replay):
    _, data = fixture_replay
    keys = data[
        _fixture_key(
            "state_getKeysPaged",
            [networks_added_prefix_hex(), 200, None, PINNED_HASH],
        )
    ]
    netuids = sorted({netuid_from_networks_added_key(k) for k in keys if netuid_from_networks_added_key(k) != 0})
    batch_key = _fixture_key("state_queryStorageAt", [reserve_query_keys(netuids), PINNED_HASH])
    assert batch_key in data
