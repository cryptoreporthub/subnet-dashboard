"""file_lock waits only for a busy lock. Any other OS error must surface at once.

Before the fix every OSError was treated as contention, so a permanent failure
(bad fd, read-only volume, permission) spun until the timeout and was reported
as a busy lock.
"""

from __future__ import annotations

import errno
import time

import pytest

import internal.file_utils as file_utils


def test_permanent_flock_error_raises_immediately_not_as_busy(tmp_path, monkeypatch):
    def bad_fd(_fd, _op):
        raise OSError(errno.EBADF, "bad file descriptor")

    monkeypatch.setattr(file_utils.fcntl, "flock", bad_fd)
    started = time.monotonic()
    with pytest.raises(OSError) as raised:
        with file_utils.file_lock(str(tmp_path / "x.json"), timeout_seconds=5.0):
            pass
    elapsed = time.monotonic() - started

    assert not isinstance(raised.value, TimeoutError)
    assert raised.value.errno == errno.EBADF
    assert elapsed < 1.0, f"permanent error retried for {elapsed:.1f}s"


def test_busy_lock_still_times_out(tmp_path, monkeypatch):
    def busy(_fd, _op):
        raise BlockingIOError(errno.EWOULDBLOCK, "busy")

    monkeypatch.setattr(file_utils.fcntl, "flock", busy)
    with pytest.raises(TimeoutError):
        with file_utils.file_lock(str(tmp_path / "x.json"), timeout_seconds=0.2):
            pass
