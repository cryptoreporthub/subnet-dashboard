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
