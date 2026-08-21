"""Daily pick stage timing helper tests."""

import logging

from internal.council.daily_pick_timing import StageTimer, log_stage_summary, timing_enabled


def test_timing_enabled_defaults_on():
    assert timing_enabled() is True


def test_timing_enabled_respects_off(monkeypatch):
    monkeypatch.setenv("DAILY_PICK_STAGE_TIMING", "0")
    assert timing_enabled() is False


def test_stage_timer_records_ms():
    with StageTimer("x") as timer:
        pass
    assert timer.ms >= 0.0


def test_log_stage_summary_emits_warning(caplog):
    caplog.set_level(logging.WARNING)
    log_stage_summary("daily pick tick timing", {"load_subnets": 12.4, "pick_work": 90000.0}, extra={"universe": 24})
    assert any("daily pick tick timing" in rec.message for rec in caplog.records)
    assert any("load_subnets=12ms" in rec.message for rec in caplog.records)


def test_log_stage_summary_respects_disable(monkeypatch, caplog):
    monkeypatch.setenv("DAILY_PICK_STAGE_TIMING", "off")
    caplog.set_level(logging.WARNING)
    log_stage_summary("daily pick tick timing", {"pick_work": 1.0})
    assert not caplog.records
