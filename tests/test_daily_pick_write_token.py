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


def test_fence_timeout_health_flag():
    tok.revoke_daily_pick_write_token(fence_timeout=True, reason="fence")
    flags = tok.health_flags()
    assert flags.get("daily_pick_write_fence_timeout") is True
    assert flags.get("daily_pick_schedule_disabled") is True
