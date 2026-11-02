"""heavy_job_rss observability lines (#1538 PR2)."""

from __future__ import annotations

import logging

import pytest

from internal.process_memory import log_heavy_job_rss


def _heavy_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.message for r in caplog.records if "heavy_job_rss" in r.message]


def test_heavy_job_rss_success_and_exception(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="process_memory")
    monkeypatch.setattr(
        "internal.process_memory.read_rss_kb",
        lambda pid=None: 123456,
    )
    monkeypatch.setattr("internal.run_mode.get_run_mode", lambda: "worker")

    t0 = 0.0
    monkeypatch.setattr("internal.process_memory.time.perf_counter", lambda: t0)
    log_heavy_job_rss("test_job", "start", started_at=t0)
    t0 = 0.05
    monkeypatch.setattr("internal.process_memory.time.perf_counter", lambda: t0)
    log_heavy_job_rss("test_job", "end", started_at=0.0)

    lines = _heavy_lines(caplog)
    assert len(lines) == 2
    assert "phase=start" in lines[0] and "name=test_job" in lines[0]
    assert "phase=end" in lines[1] and "held_ms=" in lines[1]
    assert "rss_kb=123456" in lines[0]

    caplog.clear()
    t0 = 1.0
    monkeypatch.setattr("internal.process_memory.time.perf_counter", lambda: t0)
    log_heavy_job_rss("fail_job", "start", started_at=t0)
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        t0 = 1.02
        monkeypatch.setattr("internal.process_memory.time.perf_counter", lambda: t0)
        log_heavy_job_rss("fail_job", "end", started_at=1.0)
    lines = _heavy_lines(caplog)
    assert len(lines) == 2
    assert any("phase=start" in x for x in lines)
def test_heavy_job_rss_read_rss_raises(caplog, monkeypatch):
    caplog.set_level(logging.DEBUG, logger="process_memory")

    def _boom(_pid=None):
        raise ValueError("no proc")

    monkeypatch.setattr("internal.process_memory.read_rss_kb", _boom)
    log_heavy_job_rss("fragile", "start")
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)
