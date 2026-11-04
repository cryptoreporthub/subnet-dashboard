"""Generation-token fence tests (plan §5.1 / §7)."""

from __future__ import annotations

import threading
import time

import pytest

from internal.council import daily_pick_write_token as tok


@pytest.fixture(autouse=True)
def _fresh_token():
    tok.issue_daily_pick_write_token()
    yield
    tok.issue_daily_pick_write_token()


def test_hung_outside_lock_does_not_block_revocation():
    barrier = threading.Barrier(2, timeout=2)

    def slow_compute():
        barrier.wait()
        time.sleep(0.5)

    t = threading.Thread(target=slow_compute)
    t.start()
    barrier.wait()
    tok.revoke_daily_pick_write_token(reason="test")
    t.join(timeout=2)
    assert tok.daily_pick_write_token_allowed() is False


def test_revoke_during_commit_race():
    committed = {"v": False}

    def commit_fn():
        time.sleep(0.05)
        committed["v"] = True

    def revoker():
        time.sleep(0.02)
        tok.revoke_daily_pick_write_token(reason="race")

    t = threading.Thread(target=revoker)
    t.start()
    ok = tok.guarded_bounded_commit(commit_fn)
    t.join(timeout=2)
    assert ok or not tok.daily_pick_write_token_allowed()
    if tok.daily_pick_write_token_allowed():
        assert committed["v"] is True


def test_post_revoke_commit_rejected():
    tok.revoke_daily_pick_write_token(reason="test")
    ran = {"v": False}

    def commit_fn():
        ran["v"] = True

    assert tok.guarded_bounded_commit(commit_fn) is False
    assert ran["v"] is False


def test_resolver_fence_wait_then_revoke(monkeypatch):
    class _Sched:
        _inflight_future = None

        def __init__(self):
            self._cycle_lock = threading.Lock()
            self._cycle_lock.acquire()

    monkeypatch.setattr(
        "internal.council.resolver_scheduler.get_prediction_resolver_scheduler",
        lambda: _Sched(),
    )
    monkeypatch.setattr(
        "internal.council.daily_pick_write_token.resolver_fence_wait_seconds",
        lambda: 0.05,
    )
    monkeypatch.setattr("internal.council.daily_pick_write_token.time.sleep", lambda _: None)

    ok = tok.wait_for_resolver_cycle_before_pick(timeout_seconds=0.01, poll_seconds=0.0)
    assert ok is False
    assert tok.fence_revoke_if_resolver_wait_exceeded(reason="test") is False
    assert tok.health_flags().get("daily_pick_write_fence_timeout") is True


def test_fence_timeout_health_flag():
    tok.revoke_daily_pick_write_token(fence_timeout=True, reason="fence")
    flags = tok.health_flags()
    assert flags.get("daily_pick_write_fence_timeout") is True
    assert flags.get("daily_pick_schedule_disabled") is True


def test_orphaned_commit_rejected_after_resolver_fence_revoke(monkeypatch):
    class _Sched:
        _inflight_future = None

        def __init__(self):
            self._cycle_lock = threading.Lock()
            self._cycle_lock.acquire()

    monkeypatch.setattr(
        "internal.council.resolver_scheduler.get_prediction_resolver_scheduler",
        lambda: _Sched(),
    )
    monkeypatch.setattr(
        "internal.council.daily_pick_write_token.resolver_fence_wait_seconds",
        lambda: 0.05,
    )
    monkeypatch.setattr("internal.council.daily_pick_write_token.time.sleep", lambda _: None)

    assert tok.fence_revoke_if_resolver_wait_exceeded(reason="test") is False
    ran = {"v": False}

    def commit_fn():
        ran["v"] = True

    assert tok.guarded_bounded_commit(commit_fn) is False
    assert ran["v"] is False
    assert tok.is_daily_pick_schedule_disabled() is True


def test_pick_tick_timeout_does_not_revoke_write_token(monkeypatch):
    """90s pick-tick timeout must not fence-revoke; later guarded commits still succeed."""
    import internal.council.pick_scheduler as pick_scheduler

    pick_scheduler.stop_pick_schedulers()
    monkeypatch.setattr(
        "internal.council.daily_pick_write_token.fence_revoke_if_resolver_wait_exceeded",
        lambda **_: True,
    )

    def _hang(*_a, **_k):
        import time

        time.sleep(12)
        return {"action": "HOLD"}

    monkeypatch.setattr(
        "internal.council.daily_pick_engine.get_or_create_today_pick",
        _hang,
    )
    monkeypatch.setattr(
        "internal.council.daily_pick_engine.write_scheduler_hold",
        lambda reason, **kwargs: {"action": "HOLD", "date": "2026-08-03", "scheduler_hold": True},
    )
    monkeypatch.setattr(pick_scheduler, "_load_subnets", lambda: [{"netuid": 1}])
    monkeypatch.setattr(pick_scheduler, "_market_context", lambda _s: {})
    monkeypatch.setattr(pick_scheduler, "_today_pick_ready", lambda: False)
    monkeypatch.setattr(pick_scheduler, "_write_scheduler_state", lambda extra=None: None)
    monkeypatch.setattr(pick_scheduler, "schedule_in_seconds", lambda *_a, **_k: None)
    pick_scheduler.DAILY_PICK_TICK_TIMEOUT_SECONDS = 5

    sched = pick_scheduler.DailyPickScheduler()
    result = sched._tick(reschedule=False)
    assert "timed out" in str(result.get("error") or "")
    assert tok.daily_pick_write_token_allowed() is True
    assert tok.is_daily_pick_schedule_disabled() is False

    committed = {"v": False}

    def commit_fn():
        committed["v"] = True

    assert tok.guarded_bounded_commit(commit_fn) is True
    assert committed["v"] is True
    pick_scheduler.stop_pick_schedulers()


def test_stale_write_generation_rejected_after_bump():
    """P1-b: timed-out / bumped generation cannot commit; current generation can."""
    stale = tok.current_write_generation()
    tok.bump_write_generation(reason="simulated tick timeout")
    ran = {"v": False}

    def commit_fn():
        ran["v"] = True

    assert tok.guarded_bounded_commit(commit_fn, write_generation=stale) is False
    assert ran["v"] is False
    assert tok.guarded_bounded_commit(commit_fn) is True
    assert ran["v"] is True


def test_stop_pick_schedulers_bumps_generation(monkeypatch):
    """P1-b: stop() invalidates outstanding worker commits without revoking schedule."""
    monkeypatch.setenv("PICK_SCHEDULER_ENABLED", "on")
    import internal.council.pick_scheduler as pick_scheduler
    from unittest.mock import MagicMock

    monkeypatch.setattr(pick_scheduler, "schedule_in_seconds", MagicMock())
    pick_scheduler.stop_pick_schedulers()
    before = tok.current_write_generation()
    pick_scheduler.start_pick_schedulers(immediate=False)
    stale = tok.current_write_generation()
    pick_scheduler.stop_pick_schedulers()
    after_stop = tok.current_write_generation()
    assert after_stop > stale

    ran = {"v": False}

    def commit_fn():
        ran["v"] = True

    assert tok.guarded_bounded_commit(commit_fn, write_generation=stale) is False
    assert ran["v"] is False
    assert tok.daily_pick_write_token_allowed() is True
    pick_scheduler.start_pick_schedulers(immediate=False)
    assert tok.guarded_bounded_commit(commit_fn) is True
    assert ran["v"] is True
    pick_scheduler.stop_pick_schedulers()


def test_stop_during_subnet_load_cannot_commit_stale_generation(monkeypatch, tmp_path):
    """P1-b: generation captured at tick start; stop during load bumps gen → no commit."""
    import json
    import threading

    import internal.council.pick_scheduler as pick_scheduler

    path = tmp_path / "daily_picks.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("internal.council.daily_pick_engine.DAILY_PICKS_PATH", str(path))
    monkeypatch.setattr(
        "internal.council.daily_pick_write_token.fence_revoke_if_resolver_wait_exceeded",
        lambda **_k: True,
    )
    monkeypatch.setattr(pick_scheduler, "_market_context", lambda _s: {})
    monkeypatch.setattr(pick_scheduler, "_today_pick_ready", lambda: False)
    monkeypatch.setattr(pick_scheduler, "_write_scheduler_state", lambda extra=None: None)
    monkeypatch.setattr(pick_scheduler, "schedule_in_seconds", lambda *_a, **_k: None)

    load_started = threading.Event()
    release_load = threading.Event()

    def _slow_load():
        load_started.set()
        release_load.wait(timeout=5)
        return [{"netuid": 1, "price": 1.0}]

    monkeypatch.setattr(pick_scheduler, "_load_subnets", _slow_load)

    commits = {"n": 0}
    real_save = __import__(
        "internal.council.daily_pick_engine", fromlist=["_save"]
    )._save

    def _counting_save(records, path=None, *, write_generation=None):
        ok = real_save(records, path, write_generation=write_generation)
        if ok:
            commits["n"] += 1
        return ok

    monkeypatch.setattr("internal.council.daily_pick_engine._save", _counting_save)
    monkeypatch.setattr(
        "internal.council.daily_pick_engine.select_daily_pick",
        lambda subnets, ctx: {
            "subnet": {"netuid": 1, "name": "X"},
            "final_confidence": 0.9,
            "action": "long",
        },
    )
    monkeypatch.setattr(
        "internal.council.daily_pick_engine.directional_publish_guard",
        lambda _p: {"approved": True, "reason": ""},
    )
    monkeypatch.setattr("internal.council.daily_pick_engine.publish_gate_fraction", lambda: 0.0)

    sched = pick_scheduler.DailyPickScheduler()

    def _run_tick():
        sched._tick(reschedule=False)

    worker = threading.Thread(target=_run_tick, name="daily-pick-tick-test")
    worker.start()
    assert load_started.wait(timeout=3)
    sched.stop()
    release_load.set()
    worker.join(timeout=15)
    assert commits["n"] == 0
    assert json.loads(path.read_text()) == []


def test_save_rejects_missing_write_generation(tmp_path, monkeypatch):
    path = tmp_path / "daily_picks.json"
    monkeypatch.setattr("internal.council.daily_pick_engine.DAILY_PICKS_PATH", str(path))
    from internal.council import daily_pick_engine as engine

    assert engine._save([{"date": "2026-11-04", "action": "HOLD"}], write_generation=None) is False


def test_start_pick_schedulers_does_not_reissue_token_after_fence_revoke(monkeypatch):
    monkeypatch.setenv("PICK_SCHEDULER_ENABLED", "on")
    import internal.council.pick_scheduler as pick_scheduler
    from unittest.mock import MagicMock

    monkeypatch.setattr(pick_scheduler, "schedule_in_seconds", MagicMock())
    pick_scheduler.stop_pick_schedulers()
    pick_scheduler.start_pick_schedulers(immediate=False)
    tok.revoke_daily_pick_write_token(fence_timeout=True, reason="fence")
    assert tok.is_daily_pick_schedule_disabled() is True
    pick_scheduler.start_pick_schedulers(immediate=False)
    assert tok.is_daily_pick_schedule_disabled() is True
    assert tok.daily_pick_write_token_allowed() is False
    pick_scheduler.stop_pick_schedulers()
