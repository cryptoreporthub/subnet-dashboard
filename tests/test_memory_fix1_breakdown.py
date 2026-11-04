"""memory fix 1 (#1538): end-of-job breakdown, flagged malloc_trim, worker MALLOC_ARENA_MAX."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import internal.process_memory as pm

ROOT = Path(__file__).resolve().parent.parent


class _FakeLibc:
    def __init__(self):
        self.calls = []

    def malloc_trim(self, pad):
        self.calls.append(pad)
        return 1


@pytest.fixture
def fake_libc(monkeypatch):
    libc = _FakeLibc()
    monkeypatch.setattr("ctypes.CDLL", lambda *_a, **_k: libc)
    monkeypatch.setattr("internal.run_mode.get_run_mode", lambda: "worker")
    return libc


def _msgs(caplog):
    return [r.message for r in caplog.records]


def test_end_phase_has_breakdown_fields_start_does_not(caplog):
    caplog.set_level(logging.INFO, logger="process_memory")
    pm.log_heavy_job_rss("job_x", "start", started_at=0.0)
    pm.log_heavy_job_rss("job_x", "end", started_at=0.0)
    start, end = _msgs(caplog)
    assert "anon_kb" not in start
    for field in ("anon_kb=", "file_kb=", "threads=", "gc="):
        assert field in end
    assert "rss_kb=" in end and "held_ms=" in end


def test_breakdown_unreadable_smaps_is_unknown_not_fatal(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="process_memory")
    real_open = open

    def _open(path, *a, **k):
        if str(path).endswith("smaps_rollup"):
            raise OSError("no smaps")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", _open)
    pm.log_heavy_job_rss("job_x", "end", started_at=0.0)
    assert any("anon_kb=unknown" in m and "threads=" in m for m in _msgs(caplog))


def test_trim_flag_off_does_not_call_trim(caplog, monkeypatch, fake_libc):
    caplog.set_level(logging.INFO, logger="process_memory")
    monkeypatch.delenv("MEMORY_MALLOC_TRIM_AFTER_JOBS", raising=False)
    pm.log_heavy_job_rss("daily_pick_scheduler", "end", started_at=0.0)
    pm.log_heavy_job_rss("pump_ladder_scan", "end", started_at=0.0)
    assert fake_libc.calls == []
    assert not any("malloc_trim" in m for m in _msgs(caplog))


@pytest.mark.parametrize("name", ["daily_pick_scheduler", "pump_ladder_scan"])
def test_trim_flag_on_trims_and_logs_before_after(caplog, monkeypatch, fake_libc, name):
    caplog.set_level(logging.INFO, logger="process_memory")
    monkeypatch.setenv("MEMORY_MALLOC_TRIM_AFTER_JOBS", "1")
    pm.log_heavy_job_rss(name, "end", started_at=0.0)
    assert fake_libc.calls == [0]
    line = next(m for m in _msgs(caplog) if "malloc_trim" in m)
    assert f"name={name}" in line and "rss_before_kb=" in line and "rss_after_kb=" in line


def test_trim_flag_on_other_jobs_and_start_phase_do_not_trim(monkeypatch, fake_libc):
    monkeypatch.setenv("MEMORY_MALLOC_TRIM_AFTER_JOBS", "1")
    pm.log_heavy_job_rss("score_snapshot", "end", started_at=0.0)
    pm.log_heavy_job_rss("daily_pick_scheduler", "start", started_at=0.0)
    assert fake_libc.calls == []


def test_trim_non_glibc_is_guarded(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="process_memory")
    monkeypatch.setenv("MEMORY_MALLOC_TRIM_AFTER_JOBS", "1")

    def _boom(*_a, **_k):
        raise OSError("no libc.so.6")

    monkeypatch.setattr("ctypes.CDLL", _boom)
    pm.log_heavy_job_rss("pump_ladder_scan", "end", started_at=0.0)
    assert any("unavailable" in m for m in _msgs(caplog))
    assert any("phase=end" in m for m in _msgs(caplog))


def test_worker_entrypoints_set_arena_max_web_does_not():
    web = (ROOT / "scripts/fly_web_entrypoint.sh").read_text()
    worker_line = next(ln for ln in web.splitlines() if "env RUN_MODE=worker" in ln)
    assert 'MALLOC_ARENA_MAX="${WORKER_MALLOC_ARENA_MAX:-2}"' in worker_line
    # the web uvicorn process is not capped: only the worker launch line mentions it
    assert [ln for ln in web.splitlines() if "MALLOC_ARENA_MAX" in ln] == [worker_line]
    assert "MALLOC_ARENA_MAX" in (ROOT / "scripts/fly_worker_entrypoint.sh").read_text()
    assert "MALLOC_ARENA_MAX" not in (ROOT / "fly.toml").read_text()
