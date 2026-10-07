"""Integration: resolver, snapshot, and pump contend for heavy_job_slot in one process."""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict

import pytest

from internal.council import resolver_scheduler, score_snapshots as snaps
from internal.council import weights as council_weights
from internal.heavy_job_gate import current_holder, heavy_job_slot
from internal.pump.scheduler import PumpLadderScheduler


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def contention_paths(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(council_weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "score_snapshots.json"))


def _gate_log_messages(caplog) -> list[str]:
    return [
        r.message
        for r in caplog.records
        if r.name == "internal.heavy_job_gate"
    ]


def test_heavy_job_gate_logs_acquire_release_and_reject(caplog):
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")

    with heavy_job_slot("job_a") as ok:
        assert ok is True
        with heavy_job_slot("job_b") as blocked:
            assert blocked is False

    msgs = _gate_log_messages(caplog)
    assert any("heavy_job_slot acquire name=job_a" in m for m in msgs)
    assert any("heavy_job_slot reject name=job_b holder=job_a" in m for m in msgs)
    assert any("heavy_job_slot release name=job_a" in m and "held_ms=" in m for m in msgs)


def test_three_schedulers_wedge_while_resolver_holds_gate(
    monkeypatch, caplog, contention_paths,
):
    """Resolver holds the slot for a full cycle; snapshot and pump must skip, not wedge."""
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")
    gate_held = threading.Event()
    release_resolver = threading.Event()

    def _slow_cycle(self) -> Dict[str, Any]:
        gate_held.set()
        release_resolver.wait(timeout=5)
        return {
            "ok": True,
            "run_at": _now_iso(),
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
        }

    monkeypatch.setattr(
        resolver_scheduler.PredictionResolverScheduler,
        "_run_refresh_cycle_with_timeout",
        _slow_cycle,
    )
    monkeypatch.setattr(
        snaps,
        "write_full_universe_snapshot",
        lambda **_: (_ for _ in ()).throw(AssertionError("snapshot must not run")),
    )
    monkeypatch.setattr(
        PumpLadderScheduler,
        "_tick_body",
        lambda self: (_ for _ in ()).throw(AssertionError("pump must not run")),
    )

    resolver_sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: [{"netuid": 1, "price": 1.0}]
    )
    snap_sched = snaps.ScoreSnapshotScheduler()
    snap_sched._scoring_in_progress = lambda: False
    pump_sched = PumpLadderScheduler(refresh_minutes=20)

    resolver_thread = threading.Thread(target=resolver_sched._tick)
    resolver_thread.start()
    assert gate_held.wait(timeout=3), "resolver never acquired heavy_job_slot"
    assert current_holder() == "prediction_resolver"

    snap_out = snap_sched._tick(reschedule=False)
    pump_out = pump_sched._tick()

    assert snap_out.get("skipped") == "heavy_job_busy"
    assert pump_out.get("skipped") == "heavy_job_busy"

    msgs = _gate_log_messages(caplog)
    assert any("heavy_job_slot acquire name=prediction_resolver" in m for m in msgs)
    assert any(
        "heavy_job_slot reject name=score_snapshot holder=prediction_resolver" in m
        for m in msgs
    )
    assert any(
        "heavy_job_slot reject name=pump_ladder holder=prediction_resolver" in m
        for m in msgs
    )

    release_resolver.set()
    resolver_thread.join(timeout=5)
    assert not resolver_thread.is_alive()
    assert current_holder() is None
    msgs = _gate_log_messages(caplog)
    assert any("heavy_job_slot release name=prediction_resolver" in m for m in msgs)


def test_three_schedulers_race_one_winner_two_rejects(monkeypatch, caplog, contention_paths):
    """All three schedulers tick together; exactly one acquires, two reject with named holder."""
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")
    tick_started = threading.Event()
    allow_finish = threading.Event()

    def _resolver_cycle(self) -> Dict[str, Any]:
        tick_started.set()
        allow_finish.wait(timeout=5)
        return {
            "ok": True,
            "run_at": _now_iso(),
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
        }

    def _snapshot_write(**_kwargs) -> Dict[str, Any]:
        tick_started.set()
        allow_finish.wait(timeout=5)
        return {"ok": True, "count": 0}

    def _pump_body(self) -> Dict[str, Any]:
        tick_started.set()
        allow_finish.wait(timeout=5)
        return {"ok": True, "run_at": _now_iso()}

    monkeypatch.setattr(
        resolver_scheduler.PredictionResolverScheduler,
        "_run_refresh_cycle_with_timeout",
        _resolver_cycle,
    )
    monkeypatch.setattr(snaps, "write_full_universe_snapshot", _snapshot_write)
    monkeypatch.setattr(PumpLadderScheduler, "_tick_body", _pump_body)
    monkeypatch.setattr(PumpLadderScheduler, "_schedule_next", lambda self, _r: None)

    resolver_sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: [{"netuid": 1, "price": 1.0}]
    )
    snap_sched = snaps.ScoreSnapshotScheduler()
    snap_sched._scoring_in_progress = lambda: False
    pump_sched = PumpLadderScheduler(refresh_minutes=20)
    pump_sched._active = False

    results: Dict[str, Dict[str, Any]] = {}
    barrier = threading.Barrier(3, timeout=3)

    def _run(name: str, fn) -> None:
        barrier.wait(timeout=3)
        results[name] = fn()

    threads = [
        threading.Thread(target=_run, args=("resolver", resolver_sched._tick)),
        threading.Thread(target=_run, args=("snapshot", lambda: snap_sched._tick(reschedule=False))),
        threading.Thread(target=_run, args=("pump", pump_sched._tick)),
    ]
    for t in threads:
        t.start()
    assert tick_started.wait(timeout=3), "no scheduler acquired heavy_job_slot"
    holder = current_holder()
    assert holder in ("prediction_resolver", "score_snapshot", "pump_ladder")

    allow_finish.set()
    for t in threads:
        t.join(timeout=5)
        assert not t.is_alive()

    busy = [name for name, out in results.items() if out.get("skipped") == "heavy_job_busy"]
    assert len(busy) == 2
    assert len(results) == 3

    msgs = _gate_log_messages(caplog)
    assert any(f"heavy_job_slot acquire name={holder}" in m for m in msgs)
    for loser in busy:
        gate_name = {
            "resolver": "prediction_resolver",
            "snapshot": "score_snapshot",
            "pump": "pump_ladder",
        }[loser]
        assert any(
            f"heavy_job_slot reject name={gate_name} holder={holder}" in m for m in msgs
        )
