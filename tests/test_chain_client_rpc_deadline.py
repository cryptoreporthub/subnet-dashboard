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

    def hanging_post(endpoint, payload, timeout):
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

    def fail_post(endpoint, payload, timeout):
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

    def fake_post(endpoint, payload, timeout):
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
