"""Daily pick stage timing helper tests."""

import logging
from unittest.mock import patch

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


def test_record_hold_decision_emits_timing(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.setenv("DAILY_PICK_STAGE_TIMING", "on")
    with patch("internal.learning.trail_events.emit_trail_event"), patch(
        "internal.council.weights._load_raw", return_value={"soul_map_state": {}}
    ), patch("internal.council.weights._save_raw"), patch(
        "internal.learning.prediction_loop.record_pick_prediction"
    ):
        from internal.learning.prediction_loop import record_hold_decision

        record_hold_decision(
            candidate={"subnet": {"netuid": 9, "name": "SN9"}, "final_confidence": 0.4},
            reason="below gate",
            subnet={"netuid": 9, "name": "SN9", "price": 1.0},
        )
    assert any("record_hold_decision timing" in rec.message for rec in caplog.records)


def test_select_daily_pick_hoists_io_cache_once(monkeypatch):
    calls = {"scenario": 0, "signal": 0, "pump": 0, "soul": 0}

    def _scenario(limit=None):
        calls["scenario"] += 1
        return []

    def _signal():
        calls["signal"] += 1
        return {"hour": {}, "day": {}}

    def _pump():
        calls["pump"] += 1
        return {"subnets": {}}

    def _soul(path=None, *, copy_blob=False):
        calls["soul"] += 1
        return {"soul_map_state": {}}

    monkeypatch.setattr("internal.council.weights.load_impact_strength", lambda: 1.0)
    monkeypatch.setattr("internal.council.weights.repair_stale_contrarian_weights", lambda path=None, predictions_path=None: False)
    monkeypatch.setattr("internal.council.scenario_memory.get_scenarios", _scenario)
    monkeypatch.setattr("internal.council.weights.load_signal_weights", _signal)
    monkeypatch.setattr("internal.pump.state.load_state", _pump)
    monkeypatch.setattr("internal.council.weights._load_raw", _soul)
    monkeypatch.setattr("internal.message_intel.rollup._conviction_rows", lambda db=None: [])

    from internal.council.daily_pick import select_daily_pick

    select_daily_pick(
        [
            {"netuid": 1, "name": "A", "price": 1.0, "change_24h": 0.0},
            {"netuid": 2, "name": "B", "price": 1.0, "change_24h": 0.0},
        ],
        {},
    )
    assert calls["scenario"] == 1
    assert calls["signal"] == 1
    assert calls["pump"] == 1
    assert calls["soul"] >= 1
