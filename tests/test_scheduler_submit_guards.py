"""A hung scheduler worker must not queue a second task behind it."""

import threading

from internal.council import pick_scheduler, resolver_scheduler
from internal.pump import desk_snapshot_scheduler as desk_sched


def _named(prefix: str):
    return [th for th in threading.enumerate() if th.name.startswith(prefix)]


def test_hung_daily_pick_refuses_second_submit(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = []

    def hang(subnets, market_context=None, force=False):
        calls.append(1)
        started.set()
        assert release.wait(timeout=20)
        return {"action": "HOLD", "date": "2026-09-23", "pick": {"netuid": 1}}

    monkeypatch.setattr(
        "internal.council.daily_pick_engine.get_or_create_today_pick", hang
    )
    monkeypatch.setattr(pick_scheduler, "_load_capped_subnets", lambda: [])
    monkeypatch.setattr(pick_scheduler, "_market_context", lambda _s: {})
    monkeypatch.setattr(pick_scheduler, "_today_pick_ready", lambda: False)
    monkeypatch.setattr(pick_scheduler, "_record_ab_benchmark", lambda *_a, **_k: None)
    monkeypatch.setattr(pick_scheduler, "_write_scheduler_state", lambda _p: None)
    monkeypatch.setattr(pick_scheduler, "DAILY_PICK_TICK_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(
        "internal.council.daily_pick_engine.write_scheduler_hold",
        lambda reason: {"action": "HOLD", "date": "2026-09-23"},
    )

    sched = pick_scheduler.DailyPickScheduler()
    box = {}

    def first():
        box["result"] = sched._tick(reschedule=False)

    worker = threading.Thread(target=first, name="daily-pick-test-driver")
    worker.start()
    assert started.wait(timeout=2)
    second = sched._tick(reschedule=False)
    third = sched._tick(reschedule=False)
    assert second["skipped"] == "previous_cycle_inflight"
    assert third["skipped"] == "previous_cycle_inflight"
    assert len(_named("daily-pick-work")) == 1
    assert calls == [1]
    worker.join(timeout=15)
    assert worker.is_alive() is False
    assert "timed out" in str(box["result"].get("error"))
    assert sched._inflight_future is not None
    assert sched._inflight_future.done() is False
    refused = sched._tick(reschedule=False)
    assert refused["skipped"] == "previous_cycle_inflight"
    assert calls == [1]
    release.set()
    sched._inflight_future.result(timeout=5)
    recovered = sched._tick(reschedule=False)
    assert recovered.get("skipped") != "previous_cycle_inflight"
    assert calls == [1, 1]
    assert recovered["ok"] is True


def test_hung_resolver_refuses_second_submit(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = []

    def hang(self):
        calls.append(1)
        started.set()
        assert release.wait(timeout=15)
        return {"ok": True, "resolved_now": 0, "expired_now": 0, "pending": 0}

    monkeypatch.setattr(resolver_scheduler, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 1)
    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    monkeypatch.setattr(sched, "_run_refresh_cycle", hang.__get__(sched, type(sched)))
    monkeypatch.setattr(sched, "_persist_cycle_summary", lambda *a, **k: None)
    box = {}

    def first():
        box["result"] = sched._run_refresh_cycle_with_timeout()

    worker = threading.Thread(target=first, name="resolver-test-driver")
    worker.start()
    assert started.wait(timeout=2)
    second = sched._run_refresh_cycle_with_timeout()
    third = sched._run_refresh_cycle_with_timeout()
    assert second == {"ok": False, "skipped": "previous_cycle_inflight"}
    assert third == {"ok": False, "skipped": "previous_cycle_inflight"}
    assert len(_named("resolver-cycle-work")) == 1
    assert calls == [1]
    worker.join(timeout=10)
    assert worker.is_alive() is False
    assert str(box["result"].get("error", "")).startswith("cycle_timeout_")
    assert sched._inflight_future.done() is False
    release.set()
    sched._inflight_future.result(timeout=5)
    started.clear()
    recovered = sched._run_refresh_cycle_with_timeout()
    assert started.wait(timeout=2)
    assert recovered.get("skipped") != "previous_cycle_inflight"
    assert len(calls) == 2
    release.set()
    sched._inflight_future.result(timeout=5)


def test_hung_desk_snapshot_refuses_second_submit(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = []

    def hang(save=True):
        calls.append(1)
        started.set()
        assert release.wait(timeout=15)
        return {"alert_level": "ok", "path": "x", "actionable_badges": []}

    monkeypatch.setattr(desk_sched, "SNAPSHOT_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr("internal.pump.desk_snapshot.run_snapshot", hang)
    sched = desk_sched.PumpDeskSnapshotScheduler(interval_minutes=15)
    box = {}

    def first():
        box["result"] = sched._run_snapshot_with_timeout()

    worker = threading.Thread(target=first, name="desk-test-driver")
    worker.start()
    assert started.wait(timeout=2)
    second = sched._run_snapshot_with_timeout()
    third = sched._run_snapshot_with_timeout()
    assert second == {"ok": False, "skipped": "previous_cycle_inflight"}
    assert third == {"ok": False, "skipped": "previous_cycle_inflight"}
    assert len(_named("desk-snapshot-work")) == 1
    assert calls == [1]
    worker.join(timeout=10)
    assert worker.is_alive() is False
    assert str(box["result"].get("error", "")).startswith("cycle_timeout_")
    assert sched._inflight_future.done() is False
    release.set()
    sched._inflight_future.result(timeout=5)
    started.clear()
    recovered = sched._run_snapshot_with_timeout()
    assert started.wait(timeout=2)
    assert recovered.get("skipped") != "previous_cycle_inflight"
    assert len(calls) == 2
    release.set()
    sched._inflight_future.result(timeout=5)
