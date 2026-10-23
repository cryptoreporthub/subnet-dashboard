import fcntl
import json
import threading

import pytest

from internal import liveness
from internal.council import daily_pick, daily_pick_engine, pick_score_cache, pick_scheduler


def _rows(count=6):
    return [
        {"netuid": i, "name": f"sn{i}", "symbol": f"S{i}", "price": 1.0, "price_change_24h": 1.0}
        for i in range(1, count + 1)
    ]


@pytest.fixture
def tick(tmp_path, monkeypatch):
    soul = tmp_path / "soul.json"

    def _read():
        try:
            return json.loads(soul.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write(mutator):
        blob = _read() or {}
        mutator(blob)
        soul.write_text(json.dumps(blob), encoding="utf-8")

    monkeypatch.setattr(liveness, "write_soul_map", _write)
    monkeypatch.setattr(liveness, "read_soul_map", _read)

    cache_path = str(tmp_path / "pick_score_cache.json")
    monkeypatch.setattr(pick_score_cache, "CACHE_PATH", cache_path)
    monkeypatch.setattr(pick_score_cache, "LOCK_PATH", cache_path + ".lock")
    pick_score_cache.clear_for_tests()
    monkeypatch.setattr(daily_pick, "LATENCY_PATH", str(tmp_path / "lat.jsonl"))
    monkeypatch.setattr(daily_pick_engine, "DAILY_PICKS_PATH", str(tmp_path / "daily_picks.json"))
    monkeypatch.setattr(daily_pick_engine, "publish_gate_fraction", lambda: 0.0)
    monkeypatch.setattr(
        daily_pick_engine, "directional_publish_guard", lambda _pick: {"approved": True, "reason": ""}
    )
    monkeypatch.setattr(
        daily_pick,
        "score_subnet_for_day",
        lambda sn, ctx: {
            "total_score": float(sn["netuid"]),
            "confidence": 0.5,
            "expert_contributions": {"quant": 0.1},
            "scenario_tags": {},
        },
    )
    monkeypatch.setattr(daily_pick, "tradable_subnets", lambda s: s)
    monkeypatch.setattr(daily_pick_engine, "tradable_subnets", lambda s: s)
    monkeypatch.setattr(
        daily_pick,
        "audit_daily_pick",
        lambda candidate, universe: {"approved": True, "adjusted_confidence": 0.5},
    )
    monkeypatch.setattr(daily_pick, "attach_council_prediction", lambda *a, **k: {})
    monkeypatch.setattr(daily_pick, "pick_reasons", lambda *a, **k: [])
    monkeypatch.setattr(
        daily_pick,
        "unpack_score_learning_fields",
        lambda payload: {"signal_impact": None, "signal_contributions": None, "active_signals": []},
    )
    monkeypatch.setattr(daily_pick_engine, "classify_regime", lambda ctx: "neutral")
    monkeypatch.setattr(daily_pick_engine, "get_rotation_summary", lambda s: {})
    monkeypatch.setattr("internal.indicators.tmc_singleflight.install_once", lambda: None)
    monkeypatch.setattr("internal.indicators.tmc_singleflight.prewarm", lambda: True)
    monkeypatch.setattr(
        "internal.learning.prediction_loop.record_pick_prediction", lambda *a, **k: {"id": "p"}
    )
    monkeypatch.setattr(
        "internal.learning.prediction_loop.record_hold_decision", lambda *a, **k: {"id": "h"}
    )
    monkeypatch.setattr(pick_scheduler, "_load_subnets", lambda: _rows())
    monkeypatch.setattr(pick_scheduler, "_market_context", lambda subnets: {})
    monkeypatch.setattr(pick_scheduler, "_record_ab_benchmark", lambda *a, **k: None)
    monkeypatch.setattr(pick_scheduler, "_write_scheduler_state", lambda state: None)
    monkeypatch.setattr(pick_scheduler, "DAILY_PICK_TICK_TIMEOUT_SECONDS", 5)

    def run():
        scheduler = pick_scheduler.DailyPickScheduler()
        result = scheduler._tick(reschedule=False)
        return scheduler, result

    return run


def _drain(scheduler):
    fut = scheduler._inflight_future
    if fut is not None:
        fut.result(timeout=15)


def test_stalled_prewarm_is_named_in_the_timeout_error(tick, monkeypatch):
    release = threading.Event()

    def hang_in_prewarm():
        release.wait(timeout=30)
        return True

    monkeypatch.setattr("internal.indicators.tmc_singleflight.prewarm", hang_in_prewarm)
    scheduler = None
    try:
        scheduler, result = tick()
    finally:
        release.set()
    _drain(scheduler)

    assert "timed out" in result["error"]
    assert "tmc_prewarm" in result["error"]
    assert "hang_in_prewarm" in result["error"]
    assert "enrich_context" in result["stages"]["done"]
    assert "tmc_prewarm" in result["stages"]["running"]


def test_a_held_cache_lock_is_named_in_the_timeout_error(tick, tmp_path):
    lock_path = pick_score_cache.LOCK_PATH
    holder = open(lock_path, "a", encoding="utf-8")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
    scheduler = None
    try:
        scheduler, result = tick()
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()
    _drain(scheduler)

    assert "timed out" in result["error"]
    assert "cache_begin" in result["error"]
    assert "_with_file_lock" in result["error"]


def test_a_finished_tick_reports_every_stage_it_ran(tick):
    scheduler, result = tick()

    assert result["ok"] is True
    done = result["stages"]["done"]
    for stage in ("enrich_context", "tmc_prewarm", "cache_begin", "score", "cache_end", "publish_save"):
        assert stage in done
        assert done[stage] >= 0.0
    assert result["stages"]["running"] == {}
