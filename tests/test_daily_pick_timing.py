"""Daily pick stage timing helper tests."""

import logging

from internal.council.daily_pick_timing import (
    StageTimer,
    TickProfile,
    begin_tick_profile,
    end_tick_profile,
    log_stage_summary,
    log_tick_profile,
    timing_enabled,
)


def test_timing_enabled_defaults_on():
    assert timing_enabled() is True


def test_timing_enabled_respects_off(monkeypatch):
    monkeypatch.setenv("DAILY_PICK_STAGE_TIMING", "0")
    assert timing_enabled() is False


def test_stage_timer_records_ms():
    with StageTimer("x") as timer:
        pass
    assert timer.ms >= 0.0


def test_tick_profile_subnet_stats():
    profile = TickProfile()
    profile.record_subnet(1, 100.0, {"technical": 40.0})
    profile.record_subnet(2, 120.0, {"technical": 50.0})
    stats = profile.subnet_stats()
    assert stats["count"] == 2
    assert stats["min_ms"] == 100
    assert stats["max_ms"] == 120


def test_log_stage_summary_emits_warning(caplog):
    caplog.set_level(logging.WARNING)
    log_stage_summary("daily pick tick timing", {"load_subnets": 12.4, "pick_work": 90000.0}, extra={"universe": 24})
    assert any("daily pick tick timing" in rec.message for rec in caplog.records)


def test_log_tick_profile_emits_warning(caplog):
    caplog.set_level(logging.WARNING)
    profile = begin_tick_profile()
    assert profile is not None
    profile.conviction_rows_calls = 1
    profile.record_subnet(19, 5000.0, {"memory": 4000.0, "technical": 200.0})
    log_tick_profile("select_daily_pick profile", end_tick_profile())
    assert any("select_daily_pick profile" in rec.message for rec in caplog.records)
    assert any("conviction_calls=1" in rec.message for rec in caplog.records)


def test_log_stage_summary_respects_disable(monkeypatch, caplog):
    monkeypatch.setenv("DAILY_PICK_STAGE_TIMING", "off")
    caplog.set_level(logging.WARNING)
    log_stage_summary("daily pick tick timing", {"pick_work": 1.0})
    assert not caplog.records
