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
    for field in ("anon_kb=", "file_kb=", "smaps_ms=", "threads=", "gc=", "arena_max=", "mi_arena_kb="):
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


def test_end_line_still_emitted_when_rss_unreadable(caplog, monkeypatch):
    """Documents the contract: rss_kb=unknown end lines were already emitted before fix 1 (old code
    logged then returned); no repo consumer treats them as a dead worker (the fly-logs-stream summary
    regex only matches rss_kb=<digits>, so unknown lines are skipped). Fix 1 only adds fields."""
    caplog.set_level(logging.INFO, logger="process_memory")
    monkeypatch.setattr("internal.process_memory.read_rss_kb", lambda pid=None: None)
    pm.log_heavy_job_rss("job_x", "end", started_at=0.0)
    line = next(m for m in _msgs(caplog) if "phase=end" in m)
    assert "rss_kb=unknown" in line and "anon_kb=" in line and "threads=" in line
    import re

    summary_re = re.compile(r"pid=(\d+).*rss_kb=(\d+)")  # same shape as fly-logs-stream-readonly.yml
    assert summary_re.search(line) is None


def test_mallinfo2_fields_on_this_host_or_unknown():
    out = pm._read_mallinfo2()
    keys = ("mi_arena_kb", "mi_hblkhd_kb", "mi_uord_kb", "mi_ford_kb", "mi_keep_kb")
    assert all(f"{k}=" in out for k in keys)
    vals = [p.split("=")[1] for p in out.split()]
    assert all(v == "unknown" or v.isdigit() for v in vals)


def test_mallinfo2_missing_symbol_is_unknown(monkeypatch):
    class _NoSymbol:
        def __getattr__(self, name):
            raise AttributeError(name)

    monkeypatch.setattr("ctypes.CDLL", lambda *_a, **_k: _NoSymbol())
    out = pm._read_mallinfo2()
    assert out.count("=unknown") == 5


def test_mallinfo2_cdll_oserror_is_unknown(monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("no libc.so.6")

    monkeypatch.setattr("ctypes.CDLL", _boom)
    assert pm._read_mallinfo2().count("=unknown") == 5


def test_arena_max_reported_from_env(monkeypatch):
    monkeypatch.setenv("MALLOC_ARENA_MAX", "2")
    assert "arena_max=2" in pm._read_mem_breakdown()
    monkeypatch.delenv("MALLOC_ARENA_MAX")
    assert "arena_max=unset" in pm._read_mem_breakdown()


def test_smaps_unicode_error_is_unknown(monkeypatch):
    real_open = open

    def _open(path, *a, **k):
        if str(path).endswith("smaps_rollup"):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", _open)
    out = pm._read_mem_breakdown()
    assert "anon_kb=unknown" in out and "smaps_ms=" in out


# --- trim allowlist: exact names, matching what the callers really emit ---------------------------


def test_trim_allowlist_is_exactly_the_two_whole_job_names():
    assert pm._TRIM_AFTER_JOBS == frozenset({"daily_pick_scheduler", "pump_ladder_scan"})


@pytest.mark.parametrize(
    "wrong",
    [
        "daily_pick_scheduler:market_context",  # sub-stage scope, not the whole job
        "daily_pick_scheduler:load_subnets",
        "pump_ladder",  # outer body bookend, not the scan
        "pump_ladder_scan_x",
        "hour_pick_scheduler",
        "Daily_Pick_Scheduler",
    ],
)
def test_trim_wrong_name_does_not_trim(monkeypatch, fake_libc, wrong):
    monkeypatch.setenv("MEMORY_MALLOC_TRIM_AFTER_JOBS", "1")
    pm.log_heavy_job_rss(wrong, "end", started_at=0.0)
    assert fake_libc.calls == []


def test_trim_names_match_what_callers_emit():
    """Drift guard: the allowlisted strings must appear verbatim at the real call sites."""
    pick = (ROOT / "internal/council/pick_scheduler.py").read_text()
    pump = (ROOT / "internal/pump/scheduler.py").read_text()
    assert 'heavy_job_rss_scope("daily_pick_scheduler")' in pick
    assert 'log_heavy_job_rss("pump_ladder_scan", "end"' in pump
