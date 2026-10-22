"""Probe RPC wall-clock budget (#1483 Act-on 2)."""

from __future__ import annotations

import time

import pytest
import requests

import internal.chain_client as chain_client_mod
from internal.chain_client import ChainClient
from internal.chain_rpc_errors import ChainRpcError
from internal.chain_price.reader import ChainReader


def test_call_typed_blackhole_budget_not_full_retry_wall_clock(monkeypatch):
    """Blackhole transport: 5s budget must not spend ~47s (retries × timeout + backoff)."""
    client = ChainClient(
        endpoint="http://10.255.255.1:9944",
        retries=3,
        timeout=10,
        init_volume_db=False,
    )
    budget = 5.0
    deadline = time.monotonic() + budget
    client._rpc_deadline_monotonic = deadline
    attempt_starts: list[float] = []

    def hanging_post(endpoint, payload, timeout, **kwargs):
        attempt_starts.append(time.monotonic())
        time.sleep(timeout)
        raise requests.ConnectTimeout("timed out")

    monkeypatch.setattr(chain_client_mod, "_timed_post", hanging_post)
    started = time.monotonic()
    with pytest.raises(ChainRpcError):
        client._call_typed("chain_getFinalizedHead", [])
    elapsed = time.monotonic() - started
    assert elapsed < budget + 0.75
    assert elapsed < 15.0
    assert all(t < deadline + 0.05 for t in attempt_starts)


def test_retry_backoff_not_run_after_deadline_budget(monkeypatch):
    """Fast transport failure must not sleep through multi-second backoff past expiry."""
    client = ChainClient(
        endpoint="http://deadline.example",
        retries=3,
        backoff=[10.0, 20.0, 40.0],
        timeout=10,
        init_volume_db=False,
    )
    client._rpc_deadline_monotonic = time.monotonic() + 0.05

    def fail_post(endpoint, payload, timeout, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(chain_client_mod, "_timed_post", fail_post)
    started = time.monotonic()
    with pytest.raises(ChainRpcError):
        client._call_typed("chain_getFinalizedHead", [])
    assert time.monotonic() - started < 0.2


def test_chain_reader_propagates_deadline_to_provider_clients(monkeypatch):
    slow = ChainClient(endpoint="https://slow.example", init_volume_db=False)
    fast = ChainClient(endpoint="https://fast.example", init_volume_db=False)
    posts: list[str] = []

    def fake_post(endpoint, payload, timeout, **kwargs):
        posts.append(endpoint)
        time.sleep(timeout)
        raise requests.ConnectionError("down")

    monkeypatch.setattr(chain_client_mod, "_timed_post", fake_post)
    budget = 0.2
    deadline = time.monotonic() + budget
    reader = ChainReader(
        [("slow", slow), ("fast", fast)],
        deadline_monotonic=deadline,
    )
    assert getattr(slow, "_rpc_deadline_monotonic") == deadline
    assert getattr(fast, "_rpc_deadline_monotonic") == deadline
    started = time.monotonic()
    result, outcome = reader.call("chain_getFinalizedHead", [])
    elapsed = time.monotonic() - started
    assert outcome == "rpc_error"
    assert result is None
    assert elapsed <= budget + 0.25
    assert not any("fast.example" in ep for ep in posts)


def _install_slow_drip_requests_post(monkeypatch, *, chunk_delay: float = 0.03) -> None:
    body = b'{"jsonrpc":"2.0","id":1,"result":"0xabc"}'

    def fake_post(endpoint, json=None, headers=None, timeout=None, stream=False):
        if not stream:
            return chain_client_mod.requests.post(
                endpoint, json=json, headers=headers, timeout=timeout
            )
        resp = requests.Response()
        resp.status_code = 200
        offset = 0

        def iter_content(chunk_size=4096):
            nonlocal offset
            while offset < len(body):
                time.sleep(chunk_delay)
                piece = body[offset : offset + 1]
                offset += 1
                yield piece

        resp.iter_content = iter_content
        resp.close = lambda: None
        return resp

    monkeypatch.setattr(chain_client_mod.requests, "post", fake_post)


def test_timed_post_slow_drip_aborts_at_absolute_deadline(monkeypatch):
    """P2: per-read timeout alone allows slow-drip past probe budget."""
    _install_slow_drip_requests_post(monkeypatch, chunk_delay=0.03)
    budget = 0.15
    deadline = time.monotonic() + budget
    started = time.monotonic()
    with pytest.raises(requests.Timeout):
        chain_client_mod._timed_post("http://drip.example", {}, 10.0, deadline_monotonic=deadline)
    elapsed = time.monotonic() - started
    assert elapsed <= budget + 0.08


def test_probe_slow_drip_stays_incomplete_within_budget(monkeypatch):
    """Probe registration read must not decode success after transport budget expires."""
    import internal.chain_price.reader as reader_mod
    from internal.chain_client import ChainClient

    _install_slow_drip_requests_post(monkeypatch, chunk_delay=0.03)
    slow = ChainClient(endpoint="https://slow.example", init_volume_db=False)
    monkeypatch.setattr(
        reader_mod.cfg,
        "rpc_provider_clients",
        lambda: [("slow", slow)],
    )
    budget = 0.15
    started = time.monotonic()
    from internal.subnet_universe import _default_probe_fetch

    observed, complete = _default_probe_fetch([1], deadline=time.monotonic() + budget)
    elapsed = time.monotonic() - started
    assert observed == {}
    assert complete is False
    assert elapsed <= budget + 0.12
