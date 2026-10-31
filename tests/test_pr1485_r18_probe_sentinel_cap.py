"""PR #1485 R18-3 (Claude #1533): ``_PROBE_UNKNOWN`` sentinel + cap from window start."""

from __future__ import annotations

import pytest

from internal import loop_stall_guard as g
from internal.council import score_snapshots as snaps
from tests.test_stall_guard_missing_receipt_wedge import _old_receipt, _run_guard, _wire
from tests.test_stall_guard_run_id_r12 import _flapping_hung_none_none_ticks


def test_probe_unknown_sentinel_same_progress_does_not_refresh_last_progress():
    """Unit pin: ``_PROBE_UNKNOWN`` resume with unchanged progress leaves ``last_progress``."""
    now = 9000.0
    watch = g._TickWatch(g._PROBE_UNKNOWN, 1000.0, probe_unknown=True)
    watch.token = ("rid", "5/128")
    watch.last_progress = 1500.0
    out = g._watch_active_tick(watch, (None, "5/128"), now)
    assert out.last_progress == 1500.0


def test_guard_probe_unknown_cap_from_window_start(tmp_path, monkeypatch):
    """Permanent probe-unknown (flap) kills at documented bound from ``first_seen``."""
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    monkeypatch.setattr(g, "INTERVAL_SECONDS", 240)
    monkeypatch.setattr(g, "CONSECUTIVE_CHECKS", 3)
    _old_receipt(6001)
    kill_at = 11
    code, _ = _flapping_hung_none_none_ticks(
        outage_every=2, ticks=kill_at, monkeypatch=monkeypatch, tmp_path=tmp_path
    )
    assert code == 1
    code_survive, _ = _flapping_hung_none_none_ticks(
        outage_every=2, ticks=kill_at - 1, monkeypatch=monkeypatch, tmp_path=tmp_path
    )
    assert code_survive is None


def _r3_sentinel_refresh_every_resume(monkeypatch) -> None:
    real = g._watch_active_tick

    def _always_refresh_progress(watch, token, now):
        if watch is not None and watch.probe_unknown and g._tokens_same_run(watch, token):
            watch.probe_unknown = False
            watch.token = token
            watch.last_progress = now
            resumed = g._token_run_id(token)
            if resumed is not None:
                watch.run_id = resumed
            return watch
        return real(watch, token, now)

    monkeypatch.setattr(g, "_watch_active_tick", _always_refresh_progress)


def test_r3_mutation_sentinel_refresh_every_resume_fails_unit_pin(tmp_path, monkeypatch):
    _r3_sentinel_refresh_every_resume(monkeypatch)
    with pytest.raises(AssertionError):
        test_probe_unknown_sentinel_same_progress_does_not_refresh_last_progress()


def test_r3_t1_mutation_already_covered_by_r15_unconditional_resume(
    tmp_path, monkeypatch
):
    """T1 (refresh every probe resume) — see ``test_unconditional_last_progress_on_resume_fails_frozen_flap_test``."""
    from tests.test_scheduler_cycle_state_typing_r15 import (
        test_unconditional_last_progress_on_resume_fails_frozen_flap_test,
    )

    test_unconditional_last_progress_on_resume_fails_frozen_flap_test(tmp_path, monkeypatch)
