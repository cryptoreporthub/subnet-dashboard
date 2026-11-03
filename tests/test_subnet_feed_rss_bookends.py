"""RSS bookends on subnet feed worker loads (#1538)."""

from __future__ import annotations

import logging

import pytest

from internal.subnets import feed as subnet_feed


def _heavy_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.message for r in caplog.records if "heavy_job_rss" in r.message]


def test_load_subnets_inner_with_rss_logs_start_and_end(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="process_memory")
    monkeypatch.setattr("internal.process_memory.read_rss_kb", lambda pid=None: 1000)
    monkeypatch.setattr("internal.run_mode.get_run_mode", lambda: "worker")
    monkeypatch.setattr(
        subnet_feed,
        "_load_subnets_inner",
        lambda: [{"netuid": 1, "name": "SN1"}],
    )

    rows = subnet_feed._load_subnets_inner_with_rss()

    assert rows == [{"netuid": 1, "name": "SN1"}]
    lines = _heavy_lines(caplog)
    assert any("name=subnet_feed_load" in x and "phase=start" in x for x in lines)
    assert any("name=subnet_feed_load" in x and "phase=end" in x for x in lines)


def test_load_subnets_inner_with_rss_import_error_uses_nullcontext(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="process_memory")
    monkeypatch.setattr(
        subnet_feed,
        "_load_subnets_inner",
        lambda: [{"netuid": 2}],
    )
    real_import = __import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "internal.process_memory":
            raise ImportError("simulated missing process_memory")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", guarded_import)

    rows = subnet_feed._load_subnets_inner_with_rss()

    assert rows == [{"netuid": 2}]
    assert not _heavy_lines(caplog)
