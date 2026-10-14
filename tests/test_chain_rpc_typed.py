"""ChainClient._call_typed and pinned read API (#1395 Step 2)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from internal.chain_client import ChainClient, PinnedBlockMismatch
from internal.chain_rpc_errors import ChainRpcError


def _client_no_volume():
    return ChainClient("https://rpc.example", init_volume_db=False)


def test_call_typed_classifies_archive_miss_4003():
    client = _client_no_volume()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"error": {"code": 4003, "message": "State already discarded"}}
    resp.raise_for_status = MagicMock()
    with patch("internal.chain_client.requests.post", return_value=resp):
        with pytest.raises(ChainRpcError) as exc:
            client._call_typed("state_queryStorageAt", [["0x01"], "0xabc"])
    assert exc.value.kind == "archive_miss"


def test_call_typed_classifies_archive_miss_code_1():
    client = _client_no_volume()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "error": {"code": 1, "message": 'UnknownBlock("State already discarded")'},
    }
    resp.raise_for_status = MagicMock()
    with patch("internal.chain_client.requests.post", return_value=resp):
        with pytest.raises(ChainRpcError) as exc:
            client._call_typed("swap_currentAlphaPrice", [64, "0xabc"])
    assert exc.value.kind == "archive_miss"


def test_call_typed_unknown_block_4001():
    client = _client_no_volume()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"error": {"code": 4001, "message": "UnknownBlock: Header was not found"}}
    resp.raise_for_status = MagicMock()
    with patch("internal.chain_client.requests.post", return_value=resp):
        with pytest.raises(ChainRpcError) as exc:
            client._call_typed("chain_getHeader", ["0xdead"])
    assert exc.value.kind == "unknown_block"


def test_call_typed_429_no_retry():
    client = _client_no_volume()
    client.retries = 3
    resp = MagicMock()
    resp.status_code = 429
    with patch("internal.chain_client.requests.post", return_value=resp) as post:
        with pytest.raises(ChainRpcError) as exc:
            client._call_typed("chain_getBlockHash", [])
    assert exc.value.kind == "rate_limited"
    assert post.call_count == 1


def test_call_typed_retries_5xx():
    client = _client_no_volume()
    client.retries = 2
    bad = MagicMock()
    bad.status_code = 503
    good = MagicMock()
    good.status_code = 200
    good.json.return_value = {"result": "0x01"}
    good.raise_for_status = MagicMock()
    with patch("internal.chain_client.requests.post", side_effect=[bad, good]) as post:
        assert client._call_typed("chain_getBlockHash", []) == "0x01"
    assert post.call_count == 2


def test_query_storage_at_rejects_block_mismatch():
    client = _client_no_volume()
    with patch.object(
        client,
        "_call_typed",
        return_value=[{"block": "0xdeadbeef", "changes": []}],
    ):
        with pytest.raises(PinnedBlockMismatch):
            client.query_storage_at(["0x01"], "0xabc")


def test_fixture_error_codes_classify():
    from internal.chain_rpc_errors import classify_jsonrpc_error

    data = json.loads(
        (Path(__file__).parent / "fixtures" / "chain" / "rpc_error_responses.json").read_text()
    )
    assert classify_jsonrpc_error(data["archive_4003"]) == "archive_miss"
    assert classify_jsonrpc_error(data["archive_code_1"]) == "archive_miss"
    assert classify_jsonrpc_error(data["unknown_4001"]) == "unknown_block"
    assert classify_jsonrpc_error(data["rate_limit"]) == "rate_limited"


def test_query_storage_at_accepts_matching_block():
    client = _client_no_volume()
    hash_ = "0xABC"
    with patch.object(
        client,
        "_call_typed",
        return_value=[{"block": hash_, "changes": [["0x01", "0x02"]]}],
    ):
        batch = client.query_storage_at(["0x01"], hash_)
    assert batch[0]["changes"][0][1] == "0x02"


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_call_typed_4xx_raises_without_retry(status):
    client = _client_no_volume()
    client.retries = 3
    resp = MagicMock()
    resp.status_code = status
    # Real requests semantics: raise_for_status() raises on 4xx, so a retry would show up as extra calls.
    resp.raise_for_status = MagicMock(side_effect=requests.HTTPError(f"HTTP {status}"))
    with patch("internal.chain_client.requests.post", return_value=resp) as post:
        with pytest.raises(ChainRpcError) as exc:
            client._call_typed("chain_getBlockHash", [])
    assert post.call_count == 1
    assert exc.value.kind == "rpc_error"
    assert exc.value.code == status


def test_call_typed_408_is_retried():
    client = _client_no_volume()
    client.retries = 2
    client.backoff = [0.0]
    timeout = MagicMock()
    timeout.status_code = 408
    timeout.raise_for_status = MagicMock(side_effect=requests.HTTPError("408"))
    good = MagicMock()
    good.status_code = 200
    good.json.return_value = {"result": "0x01"}
    good.raise_for_status = MagicMock()
    with patch("internal.chain_client.requests.post", side_effect=[timeout, good]) as post:
        assert client._call_typed("chain_getBlockHash", []) == "0x01"
    assert post.call_count == 2


def test_query_storage_at_rejects_missing_block():
    client = _client_no_volume()
    with patch.object(
        client,
        "_call_typed",
        return_value=[{"changes": [["0x01", "0x02"]]}],
    ):
        with pytest.raises(ChainRpcError) as exc:
            client.query_storage_at(["0x01"], "0xabc")
    assert exc.value.kind == "invalid"
    assert not isinstance(exc.value, PinnedBlockMismatch)


def test_storage_block_matches_fails_closed():
    from internal.chain_rpc_errors import storage_block_matches

    assert storage_block_matches({"block": "0xABC", "changes": []}, "abc")
    assert not storage_block_matches({"changes": []}, "0xabc")
    assert not storage_block_matches({"block": "", "changes": []}, "0xabc")
    assert not storage_block_matches(None, "0xabc")
    assert not storage_block_matches({"block": "0xdef"}, "0xabc")


def test_membership_rejects_missing_block():
    from internal.chain_price.membership import get_member_netuids

    def call(method, params):
        if method == "state_getKeysPaged":
            return ["0x" + "11" * 40], "ok"
        return [{"changes": [["0x" + "11" * 40, "0x01"]]}], "ok"

    assert get_member_netuids(call, "0xabc") == ([], "invalid")


def test_membership_rejects_block_mismatch():
    from internal.chain_price.membership import get_member_netuids

    def call(method, params):
        if method == "state_getKeysPaged":
            return ["0x" + "11" * 40], "ok"
        return [{"block": "0xdef", "changes": [["0x" + "11" * 40, "0x01"]]}], "ok"

    assert get_member_netuids(call, "0xabc") == ([], "invalid")
