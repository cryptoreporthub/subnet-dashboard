"""Subnet feed request-path guards — no merged TaoStats sleep on hot path."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest


def test_council_feed_skips_merged_data(monkeypatch):
    from internal.subnets.feed import get_council_subnet_feed

    monkeypatch.setattr(
        "internal.subnets.feed.load_subnets_source",
        lambda timeout=None: [],
    )
    monkeypatch.setattr(
        "internal.subnets.feed._registry_fallback_rows",
        lambda: [{"netuid": 3, "name": "Gamma"}],
    )

    def _boom():
        raise AssertionError("get_merged_subnet_data must not run on request path")

    monkeypatch.setattr("fetchers.merged_data.get_merged_subnet_data", _boom)

    rows, source = get_council_subnet_feed()
    assert source == "registry"
    assert rows and rows[0]["netuid"] == 3


def test_load_subnets_source_skips_nested_pool_on_worker_thread(monkeypatch):
    from internal.subnets.feed import load_subnets_source

    called = {"inner": False, "pool": False}

    def _inner():
        called["inner"] = True
        return [{"netuid": 1}]

    class _BoomPool:
        def __init__(self, *args, **kwargs):
            called["pool"] = True

        def submit(self, fn):
            raise AssertionError("nested pool")

        def shutdown(self, **kwargs):
            pass

    monkeypatch.setattr("internal.subnets.feed._load_subnets_inner", _inner)
    monkeypatch.setattr("internal.subnets.feed._on_pool_thread", lambda: True)
    monkeypatch.setattr("internal.subnets.feed.ThreadPoolExecutor", _BoomPool)

    rows = load_subnets_source(timeout=2)
    assert called["inner"]
    assert not called["pool"]
    assert rows


def test_load_subnets_source_uses_pool_on_main_thread(monkeypatch):
    from internal.subnets.feed import load_subnets_source

    monkeypatch.setattr(
        "internal.subnets.feed._load_subnets_inner",
        lambda: [{"netuid": 2}],
    )
    monkeypatch.setattr("internal.subnets.feed._on_pool_thread", lambda: False)

    rows = load_subnets_source(timeout=2)
    assert rows and rows[0]["netuid"] == 2


def test_subnets_handler_returns_registry_under_timeout(monkeypatch):
    from fastapi.testclient import TestClient

    import server as srv

    async def _instant_timeout(fn, timeout_s, *, label):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(srv, "_to_thread_timeout", _instant_timeout)
    monkeypatch.setattr(
        srv,
        "_list_subnets_registry_fallback",
        lambda _request, status="success": {
            "status": status,
            "meta": {"total": 1, "source": "registry"},
            "subnets": [{"netuid": 1}],
        },
    )

    resp = TestClient(srv.app).get("/api/subnets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["subnets"]
    assert body["status"] == "timeout"
