"""PR #1485 R17: progress-component ``last_progress`` + active-tick stale disk probe-unknown."""

from __future__ import annotations

import json

import pytest

from internal import loop_stall_guard as g
from internal.council import score_snapshots as snaps
from internal.council import weights
from internal.council.scheduler_cycle_state import (
    CycleStateUnreadableError,
    read_last_cycle_with_status,
)
from tests.test_scheduler_cycle_state_phase_null_r16 import PRE_R15_WRITER_LAST_CYCLE
from tests.test_stall_guard_missing_receipt_wedge import _old_receipt, _run_guard, _wire
from tests.test_stall_guard_run_id_r12 import _documented_flap_kill_bound_checks


def _wire_paths(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    state = tmp_path / "score_snapshot_scheduler.json"
    monkeypatch.setenv("SCORE_SNAPSHOT_SCHEDULER_STATE_PATH", str(state))
    return soul, state


def test_observe_run_id_clobber_same_progress_does_not_refresh_last_progress():
    watch = g._TickWatch(("rid", "2/128"), 1000.0)
    watch.observe((None, "2/128"), 2000.0)
    assert watch.last_progress == 1000.0
    assert watch.token == (None, "2/128")


def test_observe_progress_change_refreshes_last_progress():
    watch = g._TickWatch(("rid", "2/128"), 1000.0)
    watch.observe((None, "3/128"), 2000.0)
    assert watch.last_progress == 2000.0


def test_watch_active_tick_probe_resume_clobber_does_not_refresh_last_progress():
    now = 5000.0
    watch = g._TickWatch(g._PROBE_UNKNOWN, 1000.0, probe_unknown=True)
    watch.run_id = "rid"
    watch.token = ("rid", "2/128")
    watch.last_progress = 1200.0
    out = g._watch_active_tick(watch, (None, "2/128"), now)
    assert out.last_progress == 1200.0
    assert out.token == (None, "2/128")
    assert out.probe_unknown is False


def test_watch_active_tick_probe_resume_progress_change_refreshes_last_progress():
    now = 5000.0
    watch = g._TickWatch(g._PROBE_UNKNOWN, 1000.0, probe_unknown=True)
    watch.run_id = "rid"
    watch.token = ("rid", "2/128")
    watch.last_progress = 1200.0
    out = g._watch_active_tick(watch, (None, "3/128"), now)
    assert out.last_progress == now


def test_mutation_fix1_full_token_compare_fails_clobber_observe():
    real_observe = g._TickWatch.observe

    def _bad_observe(self, token, now):
        if token != self.token:
            self.token = token
            self.last_progress = now

    g._TickWatch.observe = _bad_observe  # type: ignore[method-assign]
    try:
        with pytest.raises(AssertionError):
            test_observe_run_id_clobber_same_progress_does_not_refresh_last_progress()
    finally:
        g._TickWatch.observe = real_observe  # type: ignore[method-assign]


@pytest.mark.parametrize("channel", ["new", "legacy"])
def test_active_tick_pre_r15_null_phase_on_disk_is_probe_unknown_not_idle(
    tmp_path, monkeypatch, channel
):
    soul, state = _wire_paths(tmp_path, monkeypatch)
    if channel == "new":
        state.write_text(json.dumps({"last_cycle": PRE_R15_WRITER_LAST_CYCLE}), encoding="utf-8")
    else:
        soul.write_text(
            json.dumps({"score_snapshot_scheduler": {"last_cycle": PRE_R15_WRITER_LAST_CYCLE}}),
            encoding="utf-8",
        )
        state.write_text("{}", encoding="utf-8")
    assert read_last_cycle_with_status()[1] == "ok"
    monkeypatch.setattr(snaps, "_TICK_ACTIVE", True)
    with pytest.raises(CycleStateUnreadableError):
        snaps.producer_tick_progress()


def test_active_tick_non_scoring_phase_on_disk_is_probe_unknown(tmp_path, monkeypatch):
    _, state = _wire_paths(tmp_path, monkeypatch)
    state.write_text(
        json.dumps(
            {
                "last_cycle": {
                    "run_at": "2026-10-30T12:00:00Z",
                    "ok": True,
                    "phase": "complete",
                    "run_id": "r1",
                    "progress": "128/128",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(snaps, "_TICK_ACTIVE", True)
    with pytest.raises(CycleStateUnreadableError):
        snaps.producer_tick_progress()


def _assert_guard_survives_before_absolute_cap(tmp_path, monkeypatch, *, channel: str) -> None:
    _wire(tmp_path, monkeypatch)
    from tests.test_pr1485_r18_cap_kill_null_phase import _scheduler_state_path, _seed_disk

    _scheduler_state_path(tmp_path, monkeypatch)
    _seed_disk(tmp_path, monkeypatch, channel=channel, shape="null")
    if channel == "legacy":
        assert read_last_cycle_with_status()[1] == "ok"
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    monkeypatch.setattr(g, "INTERVAL_SECONDS", 240)
    monkeypatch.setattr(g, "CONSECUTIVE_CHECKS", 3)
    monkeypatch.setattr(snaps, "_TICK_ACTIVE", True)
    _old_receipt(6001)
    cap_checks = int(g.tick_max_seconds() // g.INTERVAL_SECONDS)
    survive = cap_checks + g.CONSECUTIVE_CHECKS - 1
    code, _ = _run_guard(monkeypatch, ticks=survive)
    assert code is None


@pytest.mark.parametrize("channel", ["new", "legacy"])
def test_guard_active_tick_stale_null_phase_survives_before_absolute_cap(
    tmp_path, monkeypatch, channel
):
    _assert_guard_survives_before_absolute_cap(tmp_path, monkeypatch, channel=channel)


def test_mutation_fix2_idle_token_on_active_stale_disk_fails_guard_cap(tmp_path, monkeypatch):
    real = snaps.producer_tick_progress

    def _pre_r17_idle_when_not_scoring():
        with snaps._lock:
            active = snaps._TICK_ACTIVE
        if not active:
            return None
        last, status = read_last_cycle_with_status()
        if status == "unreadable":
            raise CycleStateUnreadableError("unreadable")
        if last.get("phase") == "scoring":
            return {"token": (last.get("run_id"), last.get("progress"))}
        return {"token": None}

    monkeypatch.setattr(snaps, "producer_tick_progress", _pre_r17_idle_when_not_scoring)
    with pytest.raises(AssertionError):
        _assert_guard_survives_before_absolute_cap(tmp_path, monkeypatch, channel="new")


@pytest.mark.parametrize("outage_every", [2, 3, 4, 5])
def test_probe_unknown_flap_fuzz_worst_kill_checks(tmp_path, monkeypatch, outage_every):
    """Report table: kill tick per outage (frozen identity-less write)."""
    from tests.test_stall_guard_run_id_r12 import _flapping_hung_none_none_ticks

    bound = _documented_flap_kill_bound_checks(outage_every)
    code, _ = _flapping_hung_none_none_ticks(
        outage_every=outage_every, ticks=bound, monkeypatch=monkeypatch, tmp_path=tmp_path
    )
    assert code == 1
    code_survive, _ = _flapping_hung_none_none_ticks(
        outage_every=outage_every, ticks=bound - 1, monkeypatch=monkeypatch, tmp_path=tmp_path
    )
    assert code_survive is None
