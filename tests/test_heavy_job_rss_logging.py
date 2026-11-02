"""heavy_job_rss observability lines (#1538 PR2)."""

from __future__ import annotations

import logging
from io import StringIO

import pytest

import internal.process_memory as process_memory_mod
from internal.process_memory import log_heavy_job_rss, process_uptime_seconds
from internal.pump.scheduler import PumpLadderScheduler


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
    assert any("phase=end" in x for x in lines)


def test_heavy_job_rss_read_rss_raises(caplog, monkeypatch):
    caplog.set_level(logging.DEBUG, logger="process_memory")

    def _boom(_pid=None):
        raise ValueError("no proc")

    monkeypatch.setattr("internal.process_memory.read_rss_kb", _boom)
    log_heavy_job_rss("fragile", "start")
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


def test_heavy_job_rss_milestone_includes_process_uptime(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="process_memory")
    monkeypatch.setattr("internal.process_memory.read_rss_kb", lambda pid=None: 1000)
    monkeypatch.setattr("internal.run_mode.get_run_mode", lambda: "worker")
    monkeypatch.setattr(
        "internal.process_memory.process_uptime_seconds",
        lambda: 42.5,
    )

    log_heavy_job_rss("boot_import_done", "milestone")

    lines = _heavy_lines(caplog)
    assert len(lines) == 1
    assert "phase=milestone" in lines[0]
    assert "process_uptime_s=42.500" in lines[0]


def test_process_uptime_uses_proc_when_older_than_import(monkeypatch):
    clk_tck = 100

    def _sysconf(name):
        if name == "SC_CLK_TCK":
            return clk_tck
        raise ValueError(name)

    monkeypatch.setattr(process_memory_mod.os, "sysconf", _sysconf)

    stat_line = "999 (python) R 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 5000\n"

    def _fake_open(path, *args, **kwargs):
        if path == "/proc/uptime":
            return StringIO("200.0 100.0\n")
        if path == "/proc/self/stat":
            return StringIO(stat_line)
        raise OSError(path)

    monkeypatch.setattr("builtins.open", _fake_open)

    age = process_uptime_seconds()
    assert abs(age - 150.0) < 0.01


def test_pump_ladder_tick_body_with_scan_mocked(monkeypatch):
    calls: list[dict] = []

    monkeypatch.setattr(
        "internal.pump.scheduler.scan_all_subnets",
        lambda: {"ok": True, "scanned": 1},
    )

    def _record(result, sched=None):
        calls.append(result)

    monkeypatch.setattr("internal.pump.scheduler.record_ladder_scan_run", _record)
    monkeypatch.setattr(PumpLadderScheduler, "_schedule_next", lambda self, _r: None)

    sched = PumpLadderScheduler(refresh_minutes=20)
    out = sched._tick_body()

    assert out.get("ok") is True
    assert calls and calls[0].get("ok") is True


def test_pump_ladder_run_body_bounded_once(monkeypatch):
    monkeypatch.setattr(
        "internal.pump.scheduler.scan_all_subnets",
        lambda: {"ok": True, "scanned": 0},
    )
    monkeypatch.setattr("internal.pump.scheduler.record_ladder_scan_run", lambda *a, **k: None)
    monkeypatch.setattr(PumpLadderScheduler, "_schedule_next", lambda self, _r: None)

    sched = PumpLadderScheduler(refresh_minutes=20)
    out = sched._run_body_bounded()

    assert out.get("ok") is True
