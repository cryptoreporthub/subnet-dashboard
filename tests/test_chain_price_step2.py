"""Step 2 chain reader, bars, retention, status (#1395)."""

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
from internal.chain_price.bars import get_chain_bar, max_staleness_seconds, series_key
from internal.chain_price.block_resolve import clear_block_cache, resolve_block_at
from internal.chain_price.membership import (
    decode_networks_added_bool,
    decode_total_networks,
    get_member_netuids,
)
from internal.chain_price.storage_keys import total_networks_key_hex
from internal.chain_price.reader import ChainReader
from internal.chain_price.sampler import run_forward_sample
from internal.integrations.status import build_integrations_status, clear_status_cache

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "chain" / "bm_9060887.json"
PINNED_HASH = "0x9df0d42a0637e3e4628ccef850f8792b28cf0c7a1695bae73e6a9c6de989fb8c"


def _fixture_key(method: str, params: list) -> str:
    return f"{method}|{json.dumps(params)}"


@pytest.fixture
def fixture_client():
    data = json.loads(FIXTURE_PATH.read_text())

    def _call(self, method, params=None):
        params = params or []
        key = _fixture_key(method, params)
        if key not in data:
            raise RuntimeError(f"missing fixture for {key}")
        return data[key]

    from internal.chain_client import _normalize_block_hash
    from internal.chain_rpc_errors import PinnedBlockMismatch

    client = ChainClient.__new__(ChainClient)
    client.endpoint = "fixture"
    client.timeout = 1
    client.retries = 0
    client.backoff = [0]

    def _typed(method, params=None):
        return _call(client, method, params or [])

    def _query_storage_at(keys, at_hash):
        batch = _typed("state_queryStorageAt", [keys, at_hash])
        if not batch:
            raise RuntimeError("empty queryStorageAt")
        entry = batch[0]
        got = entry.get("block")
        if got and _normalize_block_hash(str(got)) != _normalize_block_hash(at_hash):
            raise PinnedBlockMismatch(at_hash, str(got))
        return batch

    client._call = _typed  # type: ignore
    client._call_typed = _typed  # type: ignore
    client.query_storage_at = _query_storage_at  # type: ignore
    return client, data


def test_decode_networks_added_bool():
    assert decode_networks_added_bool("0x01") is True
    assert decode_networks_added_bool("0x00") is False
    # Absent or malformed values are not "false": the caller must fail closed on None.
    assert decode_networks_added_bool(None) is None
    assert decode_networks_added_bool("0x") is None
    assert decode_networks_added_bool("0x02") is None


def test_block_mismatch_does_not_write(fixture_client, tmp_path):
    client, _ = fixture_client
    db_path = str(tmp_path / "chain_prices.db")

    def _bad_query(keys, at_hash):
        from internal.chain_rpc_errors import PinnedBlockMismatch

        raise PinnedBlockMismatch(at_hash, "0xdeadbeef")

    client.query_storage_at = _bad_query  # type: ignore
    reader = ChainReader([("blockmachine", client)])
    with patch.object(cfg, "forward_record_enabled", return_value=True):
        result = run_forward_sample(reader, db_path=db_path, write=True)
    assert result["outcome"] == "invalid"
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM chain_price_samples").fetchone()[0] == 0
    conn.close()


def test_reader_fallback_finney_to_blockmachine(tmp_path):
    from internal.chain_rpc_errors import ChainRpcError

    class _FailClient:
        def _call_typed(self, method, params=None):
            raise ChainRpcError("rpc_error", "down")

        def _call(self, method, params=None):
            raise RuntimeError("down")

        def query_storage_at(self, keys, at_hash):
            raise ChainRpcError("rpc_error", "down")

    class _OkClient:
        def _call_typed(self, method, params=None):
            if method == "chain_getFinalizedHead":
                return "0x01"
            return {}

        def _call(self, method, params=None):
            return self._call_typed(method, params)

        def query_storage_at(self, keys, at_hash):
            return [{"block": at_hash, "changes": []}]

    reader = ChainReader([("finney", _FailClient()), ("blockmachine", _OkClient())])
    h, outcome = reader.pin_finalized_head()
    assert outcome == "ok"
    assert h == "0x01"
    assert reader.provider_served == "blockmachine"


def test_rate_limit_cooldown_skips_provider():
    from internal.chain_rpc_errors import ChainRpcError

    class _RateClient:
        endpoint = "https://finney.example"

        def __init__(self):
            self.calls = 0

        def _call_typed(self, method, params=None):
            self.calls += 1
            raise ChainRpcError("rate_limited", "429")

        def _call(self, method, params=None):
            return self._call_typed(method, params)

        def query_storage_at(self, keys, at_hash):
            raise ChainRpcError("rate_limited", "429")

    finney = _RateClient()
    bm = _RateClient()
    bm.endpoint = "https://blockmachine.example"
    reader = ChainReader([("finney", finney), ("blockmachine", bm)])
    reader._mark_rate_limited("finney", finney)
    providers = reader._available_providers()
    assert all(label != "finney" for label, _ in providers)


def test_get_chain_bar_staleness_selector(tmp_path):
    db_path = str(tmp_path / "chain_prices.db")
    price_db.ensure_schema(db_path)
    ts = int(time.time() * 1000)
    reg = 4531295
    sk = series_key(64, reg)
    row = {
        "netuid": 64,
        "block": 1,
        "block_hash": PINNED_HASH,
        "provider": "blockmachine",
        "ts_ms": ts - 60_000,
        "registered_at": reg,
        "tao_reserve_raw": 1,
        "alpha_reserve_raw": 1,
        "price_tao": 0.07,
        "spot_price_tao": None,
        "unit": "tao",
        "quality": "chain_sampled",
        "schema_version": cfg.SCHEMA_VERSION,
        "series_key": sk,
    }
    price_db.insert_sample_rows([row], path=db_path)
    bar = get_chain_bar(64, reg, ts, horizon_s=3600, path=db_path)
    assert bar is not None
    assert bar["price_source"] == "chain_sampled"
    assert bar["series_key"] == sk
    assert max_staleness_seconds(3600) == 450


def test_status_distinguishes_network_and_provider():
    import internal.integrations.status as st

    clear_status_cache()
    # The RPC URL is read at import time, so pin the module constant rather than the env.
    with patch.object(st, "_bittensor_rpc_url", return_value=st._BLOCKMACHINE_RPC), patch.object(
        st, "_BITTENSOR_NETWORK", "finney"
    ):
        with patch("internal.integrations.status._rpc_chain_healthy", return_value=(True, "chain RPC ok")):
            with patch("internal.integrations.status._http_probe", return_value=(True, 200, "ok")):
                payload = build_integrations_status(force=True)
    finney = next(r for r in payload["integrations"] if r["slug"] == "bittensor")
    assert "via Blockmachine" in finney["detail"]
    assert "Finney mainnet" in finney["detail"]


def test_schema_version_v2_samples(fixture_client, tmp_path):
    client, _ = fixture_client
    db_path = str(tmp_path / "chain_prices.db")
    reader = ChainReader([("blockmachine", client)])
    with patch.object(cfg, "forward_record_enabled", return_value=True):
        result = run_forward_sample(reader, db_path=db_path, write=True)
    assert result["outcome"] == "ok"
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT schema_version, block_hash, series_key FROM chain_price_samples WHERE netuid=64"
    ).fetchone()
    conn.close()
    assert row[0] == 2
    assert row[1] is not None
    assert row[2] and row[2].startswith("chain:v2:64:")


def test_decode_total_networks_u16_le():
    assert decode_total_networks("0x8100") == 129
    assert decode_total_networks("0x05") is None
    assert decode_total_networks("0x810000") is None


def test_member_netuids_excludes_false_bool(fixture_client):
    client, _ = fixture_client
    reader = ChainReader([("blockmachine", client)])
    netuids, outcome = get_member_netuids(reader.call_fn(), PINNED_HASH)
    assert outcome == "ok"
    assert 64 in netuids
    assert 0 not in netuids


def _fake_membership_call(members_incl_root: int, total_networks: int, *, at_hash: str = PINNED_HASH):
    from internal.chain_price.storage_keys import map_key_hex

    non_root = members_incl_root - 1
    network_keys = [map_key_hex(b"NetworksAdded", n) for n in range(non_root + 1)]
    total_key = total_networks_key_hex()
    total_hex = "0x" + int(total_networks).to_bytes(2, "little").hex()

    def _call(method, params):
        if method == "state_getKeysPaged":
            return network_keys, "ok"
        if method == "state_queryStorageAt":
            keys, block = params[0], params[1]
            assert total_key in keys
            changes = [[k, "0x01"] for k in network_keys] + [[total_key, total_hex]]
            return [{"block": block, "changes": changes}], "ok"
        return None, "rpc_error"

    return _call


@pytest.mark.parametrize("members_incl_root", [128, 130])
def test_members_disagreeing_with_total_networks_is_a_failed_read_not_absence(members_incl_root):
    """TotalNetworks mismatch (fewer or more than NetworksAdded) is a failed read, not absence."""
    netuids, outcome = get_member_netuids(
        _fake_membership_call(members_incl_root, 129), PINNED_HASH
    )
    assert netuids == []
    assert outcome == "invalid"


def test_rate_limited_does_not_trigger_schema_miss_cancel(monkeypatch):
    from internal.chain_price import sampler as sampler_mod

    sampler_mod._consecutive_schema_miss = 0
    stopped: list[int] = []

    monkeypatch.setattr(
        "internal.chain_price.scheduler.stop_forward_recorder",
        lambda: stopped.append(1),
    )
    for _ in range(8):
        sampler_mod._bump_schema_miss("rate_limited")
    assert sampler_mod._consecutive_schema_miss == 0
    assert not stopped


def test_schema_miss_triggers_cancel_after_six(monkeypatch):
    from internal.chain_price import sampler as sampler_mod

    sampler_mod._consecutive_schema_miss = 0
    stopped: list[int] = []

    monkeypatch.setattr(
        "internal.chain_price.scheduler.stop_forward_recorder",
        lambda: stopped.append(1),
    )
    for _ in range(6):
        sampler_mod._bump_schema_miss("schema_miss")
    assert stopped


def test_resolve_block_at_uses_cache(fixture_client):
    clear_block_cache()
    client, _ = fixture_client
    reader = ChainReader([("blockmachine", client)])
    ts = 1789328964000
    block, block_hash, outcome = resolve_block_at(reader, ts, hint_block=9060887)
    assert outcome == "ok"
    assert block == 9060887
    assert block_hash == PINNED_HASH
