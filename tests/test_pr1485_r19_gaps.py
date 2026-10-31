"""PR #1485 R19: test gaps G1–G4 (legacy seed order, sentinel, silent start, R1c)."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from internal import loop_stall_guard as g
from internal.council import score_snapshots as snaps
from internal.council import weights
from internal.council.scheduler_cycle_state import write_last_cycle
from tests.test_pr1485_r18_cap_kill_null_phase import (
    _assert_cap_kill_pins,
    _disk_last_cycle,
    _guard_defaults,
    _r1a_past_absolute_cap_if_false,
    _r1b_cap_branch_not_hung,
    _r1c_age_none_clears_strikes_during_cap,
    _scheduler_state_path,
    _seed_disk,
    _wire_paths,
)
from tests.test_pr1485_r18_silent_write_deadline import _r2b_bypass_no_progress_deadline
from tests.test_scheduler_cycle_state_phase_null_r16 import PRE_R15_WRITER_LAST_CYCLE
from tests.test_stall_guard_missing_receipt_wedge import (
    _active_tick,
    _old_receipt,
    _run_guard,
    _wire,
)


def _seed_legacy_only(tmp_path, monkeypatch, *, shape: str) -> None:
    """Legacy soul_map last_cycle only — sidecar file absent (R20 wire-first)."""
    _wire(tmp_path, monkeypatch)
    _scheduler_state_path(tmp_path, monkeypatch)
    soul = Path(weights.SOUL_MAP_PATH)
    state = Path(os.environ["SCORE_SNAPSHOT_SCHEDULER_STATE_PATH"])
    payload = _disk_last_cycle(shape)
    if payload is None:
        soul.write_text("{}", encoding="utf-8")
    else:
        soul.write_text(
            json.dumps({"score_snapshot_scheduler": {"last_cycle": payload}}),
            encoding="utf-8",
        )
    state.unlink(missing_ok=True)


def test_g1_legacy_cap_kill_pins_without_sidecar_file(tmp_path, monkeypatch):
    _assert_cap_kill_pins(tmp_path, monkeypatch, channel="legacy", shape="null")


def test_g1_legacy_seed_requires_soul_path_wired_before_write(tmp_path, monkeypatch):
    """Wire ``SOUL_MAP_PATH`` before writing legacy payload (deploy order)."""
    soul = tmp_path / "soul_map.json"
    state = tmp_path / "score_snapshot_scheduler.json"
    monkeypatch.setenv("SCORE_SNAPSHOT_SCHEDULER_STATE_PATH", str(state))
    payload = _disk_last_cycle("null")
    soul.write_text(json.dumps({"score_snapshot_scheduler": {"last_cycle": payload}}))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    _wire(tmp_path, monkeypatch)
    kill_at = _guard_defaults(monkeypatch)
    monkeypatch.setattr(snaps, "_TICK_ACTIVE", True)
    _old_receipt(6001)
    assert _run_guard(monkeypatch, ticks=kill_at - 1)[0] is None
    assert _run_guard(monkeypatch, ticks=kill_at)[0] == 1


def test_g2_real_sentinel_token_until_resume():
    """Fresh probe-unknown watch keeps ``_PROBE_UNKNOWN`` as token until resume (not pre-clobbered)."""
    watch = g._TickWatch(g._PROBE_UNKNOWN, 1000.0, probe_unknown=True)
    assert watch.token is g._PROBE_UNKNOWN
    out = g._watch_active_tick(watch, (None, "5/128"), 5000.0)
    assert out.token == (None, "5/128")
    assert out.probe_unknown is False


def test_g2_probe_unknown_same_progress_does_not_refresh_last_progress():
    """Same as R18-3 unit pin — reused by G2 mutant kill."""
    now = 9000.0
    watch = g._TickWatch(g._PROBE_UNKNOWN, 1000.0, probe_unknown=True)
    watch.token = ("rid", "5/128")
    watch.last_progress = 1500.0
    out = g._watch_active_tick(watch, (None, "5/128"), now)
    assert out.last_progress == 1500.0


def test_g2_guard_loop_sentinel_path_cap_kill_check_11(tmp_path, monkeypatch):
    """Active tick + stale legacy null-phase → probe-unknown sentinel → cap kill @ check 11."""
    _assert_cap_kill_pins(tmp_path, monkeypatch, channel="legacy", shape="null")


def _g2_mutant_drop_probe_unknown_sentinel(monkeypatch) -> None:
    real_init = g._TickWatch.__init__

    def _init(self, token, now, *, probe_unknown=False):
        if token is g._PROBE_UNKNOWN:
            token = None
        real_init(self, token, now, probe_unknown=probe_unknown)

    monkeypatch.setattr(g._TickWatch, "__init__", _init)


def test_g2_mutations_fail_real_sentinel_unit_pin(monkeypatch):
    _g2_mutant_drop_probe_unknown_sentinel(monkeypatch)
    with pytest.raises(AssertionError):
        test_g2_real_sentinel_token_until_resume()


def test_g2_mutations_fail_guard_loop_sentinel_cap_kill(tmp_path, monkeypatch):
    _r1b_cap_branch_not_hung(monkeypatch)
    with pytest.raises(AssertionError):
        test_g2_guard_loop_sentinel_path_cap_kill_check_11(tmp_path, monkeypatch)


def test_g2_r3_mutations_fail_same_progress_sentinel_pin(tmp_path, monkeypatch):
    from tests.test_pr1485_r18_probe_sentinel_cap import _r3_sentinel_refresh_every_resume

    _r3_sentinel_refresh_every_resume(monkeypatch)
    with pytest.raises(AssertionError):
        test_g2_probe_unknown_same_progress_does_not_refresh_last_progress()


def _silent_start_record_only(tmp_path, monkeypatch) -> None:
    _wire(tmp_path, monkeypatch)
    _old_receipt(6001)
    _active_tick(monkeypatch)
    write_last_cycle(
        {
            "run_at": "2026-10-31T00:00:00Z",
            "run_id": uuid.uuid4().hex,
            "ok": False,
            "phase": "scoring",
        }
    )


def test_g3_silent_write_start_record_only_alive_6_killed_7(tmp_path, monkeypatch):
    """Tick-start row has ``phase=scoring`` but no ``progress`` key (write not started)."""
    _silent_start_record_only(tmp_path, monkeypatch)
    assert _run_guard(monkeypatch, ticks=6)[0] is None
    assert _run_guard(monkeypatch, ticks=7)[0] == 1


def test_g3_mutations_fail_start_record_only_pin(tmp_path, monkeypatch):
    _r2b_bypass_no_progress_deadline(monkeypatch)
    _silent_start_record_only(tmp_path, monkeypatch)
    with pytest.raises(AssertionError):
        test_g3_silent_write_start_record_only_alive_6_killed_7(tmp_path, monkeypatch)


def test_g4_r1c_distinct_from_r1b_fails_cap_kill_pin(tmp_path, monkeypatch):
    _r1c_age_none_clears_strikes_during_cap(monkeypatch)
    with pytest.raises(AssertionError):
        _assert_cap_kill_pins(tmp_path, monkeypatch, channel="new", shape="null")
    _r1b_cap_branch_not_hung(monkeypatch)
    with pytest.raises(AssertionError):
        _assert_cap_kill_pins(tmp_path, monkeypatch, channel="new", shape="null")


@pytest.mark.parametrize(
    "mutator",
    [_r1a_past_absolute_cap_if_false, _r1b_cap_branch_not_hung, _r1c_age_none_clears_strikes_during_cap],
    ids=["R1a-cap-if-false", "R1b-cap-branch-not-hung", "R1c-age-none-clears-strikes"],
)
def test_g4_r18_1_mutations_still_fail_cap_kill_pin(tmp_path, monkeypatch, mutator):
    mutator(monkeypatch)
    with pytest.raises(AssertionError):
        _assert_cap_kill_pins(tmp_path, monkeypatch, channel="new", shape="null")
