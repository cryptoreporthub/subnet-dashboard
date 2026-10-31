"""PR #1485 R18-2 (Claude #1533): silent write-phase setup — deadline vs cap pins."""

from __future__ import annotations

import pytest

from internal import loop_stall_guard as g
from internal.council import score_snapshots as snaps
from tests.test_stall_guard_missing_receipt_wedge import (
    _active_tick,
    _old_receipt,
    _run_guard,
    _scoring_progress,
    _wire,
)


def _silent_write_setup(tmp_path, monkeypatch) -> None:
    _wire(tmp_path, monkeypatch)
    _old_receipt(6001)
    _active_tick(monkeypatch)
    _scoring_progress(128, 128)


def test_silent_write_setup_alive_check_6_killed_check_7(tmp_path, monkeypatch):
    """Frozen progress during write: no exit through check 6; exit by check 7 (default deadline scale)."""
    _silent_write_setup(tmp_path, monkeypatch)
    code6, _revives6 = _run_guard(monkeypatch, ticks=6)
    assert code6 is None
    code7, revives7 = _run_guard(monkeypatch, ticks=7)
    assert code7 == 1
    assert revives7 >= 1


def test_advancing_progress_before_deadline_survives_past_check_7(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    _old_receipt(6001)
    _active_tick(monkeypatch)
    _scoring_progress(0)

    def _advance(n: int) -> None:
        _scoring_progress(n)

    assert _run_guard(monkeypatch, ticks=10, on_tick=_advance) == (None, 0)


def _r2a_fake_advancing_last_progress(monkeypatch) -> None:
    real_observe = g._TickWatch.observe

    def _always_refresh(self, token, now):
        self.token = token
        self.last_progress = now

    monkeypatch.setattr(g._TickWatch, "observe", _always_refresh)


def _r2b_bypass_no_progress_deadline(monkeypatch) -> None:
    monkeypatch.setattr(g, "tick_progress_seconds", lambda: 10**9)


@pytest.mark.parametrize(
    "mutator",
    [_r2a_fake_advancing_last_progress, _r2b_bypass_no_progress_deadline],
    ids=["R2-fake-advancing", "R2-bypass-deadline"],
)
def test_r18_2_mutations_fail_silent_write_check_7_pin(tmp_path, monkeypatch, mutator):
    mutator(monkeypatch)
    _silent_write_setup(tmp_path, monkeypatch)
    with pytest.raises(AssertionError):
        test_silent_write_setup_alive_check_6_killed_check_7(tmp_path, monkeypatch)
