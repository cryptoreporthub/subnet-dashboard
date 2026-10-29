"""_locked_score_snapshot retries lock contention only; a real flock failure surfaces as itself (#1484 Ditto r15)."""

from __future__ import annotations

import errno
import fcntl

import pytest

from internal.council import score_snapshots as ss


def test_contention_is_retried_until_the_lock_is_free(tmp_path, monkeypatch):
    real = fcntl.flock
    attempts = []

    def flaky(fd, op):
        if op & fcntl.LOCK_NB and len(attempts) < 3:
            attempts.append(op)
            raise BlockingIOError(errno.EAGAIN, "held elsewhere")
        return real(fd, op)

    monkeypatch.setattr(ss.fcntl, "flock", flaky)
    with ss._locked_score_snapshot(str(tmp_path / "snap.json"), timeout_seconds=5.0):
        pass
    assert len(attempts) == 3


def test_a_non_contention_oserror_propagates_at_once_not_as_a_timeout(tmp_path, monkeypatch):
    calls = []

    def broken(fd, op):
        calls.append(op)
        raise OSError(errno.EINVAL, "bad lock request")

    monkeypatch.setattr(ss.fcntl, "flock", broken)
    with pytest.raises(OSError) as info:
        with ss._locked_score_snapshot(str(tmp_path / "snap.json"), timeout_seconds=5.0):
            pytest.fail("the body must not run without the lock")
    assert info.value.errno == errno.EINVAL
    assert not isinstance(info.value, TimeoutError)
    assert len(calls) == 1  # no retry loop
