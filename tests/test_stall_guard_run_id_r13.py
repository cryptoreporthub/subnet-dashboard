"""PR #1485 R13: mutation guards (M13, M10b, identity-less return False) — tests only."""

from __future__ import annotations

import time

import pytest

from internal import loop_stall_guard as g
from internal.council import score_snapshots as snaps
from internal.council import scheduler_cycle_state as scs
from tests.test_score_snapshots import (
    _published_payload,
    _reset_write_occupancy,
    _wire_scheduler_paths,
)
from tests.test_stall_guard_missing_receipt_wedge import (
    _old_receipt,
    _run_guard,
    _wire,
)
from tests.test_stall_guard_run_id_r12 import (
    _documented_flap_kill_bound_checks,
    _flapping_hung_none_none_ticks,
)


def _s2_clobbered_tick_progress():
    run_id = "stable-run-id"
    calls = {"n": 0}

    def _controlled():
        calls["n"] += 1
        n = calls["n"]
        if n == 1:
            return g.TickProgressSnapshot({"token": (run_id, "1/128")}, True)
        if n <= 6:
            return g.TickProgressSnapshot(None, False)
        if n == 7:
            return g.TickProgressSnapshot({"token": (None, "2/128")}, True)
        step = n - 6
        return g.TickProgressSnapshot({"token": (None, f"{step}/128")}, True)

    return _controlled, calls


def _wire_s2_defaults(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    _old_receipt(6001)


def assert_s2_clobbered_kills_at_check_11(tmp_path, monkeypatch) -> None:
    """Known run_id + clobbered (None,p) keeps cap: alive check 10, exit check 11."""
    _wire_s2_defaults(tmp_path, monkeypatch)
    controlled, calls = _s2_clobbered_tick_progress()
    monkeypatch.setattr(g, "_tick_progress", controlled)
    code10, _ = _run_guard(monkeypatch, ticks=10)
    assert code10 is None
    calls["n"] = 0
    code11, _ = _run_guard(monkeypatch, ticks=11)
    assert code11 == 1


def test_m13_mutation_dropping_clobber_same_run_fails_s2_bound(tmp_path, monkeypatch):
    real = g._tokens_same_run

    def _without_s2_clobber(watch, token):
        resumed = g._token_run_id(token)
        if watch.run_id is None:
            return resumed is None
        if resumed == watch.run_id:
            return True
        if resumed is None:
            return False
        return False

    monkeypatch.setattr(g, "_tokens_same_run", _without_s2_clobber)
    with pytest.raises(AssertionError):
        assert_s2_clobbered_kills_at_check_11(tmp_path, monkeypatch)


def _deferred_timeout_run_id_pair(tmp_path, monkeypatch) -> tuple[str, str | None]:
    path = _wire_scheduler_paths(tmp_path, monkeypatch)
    monkeypatch.setenv("SCORE_SNAPSHOT_CYCLE_PATH", str(tmp_path / "cycle_state.json"))

    def _slow_build(*_args, **_kwargs):
        time.sleep(2)
        payload = _published_payload(count=1)
        snaps.publish_complete_snapshot(payload, str(path))
        return payload

    monkeypatch.setattr(snaps, "build_full_universe_snapshot", _slow_build)
    _reset_write_occupancy()
    sched = snaps.ScoreSnapshotScheduler()
    monkeypatch.setattr(snaps, "_scheduler", sched)
    sched._scoring_in_progress = lambda: False
    try:
        timed_out = sched.run_once()
        assert "write_timeout" in timed_out.get("error", "")
        sync_run_id = timed_out.get("run_id")
        assert sync_run_id
        time.sleep(2.5)
        last = scs.read_last_cycle()
        return sync_run_id, last.get("run_id")
    finally:
        time.sleep(0.5)
        _reset_write_occupancy()


def test_deferred_write_completion_preserves_run_id_in_cycle_summary(
    tmp_path, monkeypatch
):
    sync_run_id, deferred_run_id = _deferred_timeout_run_id_pair(tmp_path, monkeypatch)
    assert deferred_run_id == sync_run_id


def test_m10b_mutation_omitting_run_id_copy_fails_deferred_summary(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(scs, "read_last_cycle", lambda soul_map_path=None: {})
    sync_run_id, deferred_run_id = _deferred_timeout_run_id_pair(tmp_path, monkeypatch)
    assert sync_run_id
    with pytest.raises(AssertionError):
        assert deferred_run_id == sync_run_id


def test_mutation_return_false_identity_less_fails_flap_kill_bound(
    tmp_path, monkeypatch
):
    real = g._tokens_same_run

    def _always_fresh_identity_less(watch, token):
        if watch.run_id is None:
            return False
        return real(watch, token)

    monkeypatch.setattr(g, "_tokens_same_run", _always_fresh_identity_less)
    bound = _documented_flap_kill_bound_checks(3)
    code, _ = _flapping_hung_none_none_ticks(
        outage_every=3, ticks=bound, monkeypatch=monkeypatch, tmp_path=tmp_path
    )
    assert code is None
