"""Forward chain price recorder (#1395 Step 0)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from internal.chain_client import ChainClient
from internal.chain_price import config as cfg
from internal.chain_price.sampler import run_forward_sample, sample_sn64_from_block
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
    assert second["samples_written"] == count


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
