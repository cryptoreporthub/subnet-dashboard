"""PR #1485 R18-1 (Claude #1533): cap-kill pins on r17 null-phase / stale-disk probe-unknown path."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from internal import loop_stall_guard as g
from internal.council import score_snapshots as snaps
from internal.council import weights
from internal.council.scheduler_cycle_state import read_last_cycle_with_status
from tests.test_scheduler_cycle_state_phase_null_r16 import PRE_R15_WRITER_LAST_CYCLE
from tests.test_stall_guard_missing_receipt_wedge import _old_receipt, _run_guard, _wire


def _scheduler_state_path(tmp_path, monkeypatch) -> Path:
    state = tmp_path / "score_snapshot_scheduler.json"
    monkeypatch.setenv("SCORE_SNAPSHOT_SCHEDULER_STATE_PATH", str(state))
    return state


def _wire_paths(tmp_path, monkeypatch):
    """Deprecated alias — prefer ``_wire`` then ``_scheduler_state_path`` (R20 wire-first order)."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    return soul, _scheduler_state_path(tmp_path, monkeypatch)


def _disk_last_cycle(shape: str) -> dict | None:
    if shape == "null":
        return dict(PRE_R15_WRITER_LAST_CYCLE)
    if shape == "absent":
        row = {k: v for k, v in PRE_R15_WRITER_LAST_CYCLE.items() if k != "phase"}
        return row
    if shape == "failed":
        return {
            **PRE_R15_WRITER_LAST_CYCLE,
            "ok": False,
            "error": "write_timeout",
            "skipped": None,
        }
    if shape == "missing":
        return None
    raise ValueError(shape)


def _assert_legacy_cycle_read_ok(*, shape: str) -> None:
    """In-test guard: legacy null/absent/failed must read as ``status='ok'`` before guard run."""
    last, status = read_last_cycle_with_status()
    if shape == "missing":
        assert status == "missing", (status, last)
        return
    assert status == "ok", (status, last)


def _seed_disk(tmp_path, monkeypatch, *, channel: str, shape: str) -> None:
    """Write cycle disk after ``_wire`` + ``_scheduler_state_path``."""
    soul = Path(weights.SOUL_MAP_PATH)
    state = Path(os.environ["SCORE_SNAPSHOT_SCHEDULER_STATE_PATH"])
    payload = _disk_last_cycle(shape)
    if channel == "new":
        if payload is None:
            state.unlink(missing_ok=True)
        else:
            state.write_text(json.dumps({"last_cycle": payload}), encoding="utf-8")
    else:
        if payload is None:
            soul.write_text("{}", encoding="utf-8")
        else:
            soul.write_text(
                json.dumps({"score_snapshot_scheduler": {"last_cycle": payload}}),
                encoding="utf-8",
            )
        state.unlink(missing_ok=True)


def _guard_defaults(monkeypatch) -> int:
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    monkeypatch.setattr(g, "INTERVAL_SECONDS", 240)
    monkeypatch.setattr(g, "CONSECUTIVE_CHECKS", 3)
    cap_checks = int(g.tick_max_seconds() // g.INTERVAL_SECONDS)
    # First stale strike after cap, then CONSECUTIVE_CHECKS (R18-1 pin: kill at check 11 @ MC scale).
    return cap_checks + g.CONSECUTIVE_CHECKS + 1


def _assert_cap_kill_pins(tmp_path, monkeypatch, *, channel: str, shape: str) -> None:
    _wire(tmp_path, monkeypatch)
    _scheduler_state_path(tmp_path, monkeypatch)
    _seed_disk(tmp_path, monkeypatch, channel=channel, shape=shape)
    if channel == "legacy":
        _assert_legacy_cycle_read_ok(shape=shape)
    kill_at = _guard_defaults(monkeypatch)
    monkeypatch.setattr(snaps, "_TICK_ACTIVE", True)
    _old_receipt(6001)
    code_survive, _ = _run_guard(monkeypatch, ticks=kill_at - 1)
    assert code_survive is None
    code_kill, _ = _run_guard(monkeypatch, ticks=kill_at)
    assert code_kill == 1


@pytest.mark.parametrize("channel", ["new", "legacy"])
@pytest.mark.parametrize("shape", ["null", "absent", "failed", "missing"])
def test_null_phase_stale_disk_cap_kill_pins(
    tmp_path, monkeypatch, channel, shape
):
    """Real ``_guard_loop`` via ``_run_guard``: exit at cap + ``CONSECUTIVE_CHECKS``, not before."""
    _assert_cap_kill_pins(tmp_path, monkeypatch, channel=channel, shape=shape)


def _g1_mutant_legacy_branch_scoring_advance(monkeypatch) -> None:
    """Mutate legacy read to return in-flight scoring (must break probe-unknown cap pins)."""
    import internal.council.scheduler_cycle_state as cycle_state

    real = cycle_state._read_legacy_with_status

    def _scoring_legacy(soul_map_path=None):
        summary, unreadable = real(soul_map_path)
        if unreadable or not summary:
            return summary, unreadable
        return (
            {
                **summary,
                "phase": "scoring",
                "progress": "64/128",
                "run_id": "legacy-mutant-run",
                "ok": False,
            },
            False,
        )

    monkeypatch.setattr(cycle_state, "_read_legacy_with_status", _scoring_legacy)


@pytest.mark.parametrize("shape", ["null", "absent", "failed"])
def test_g1_legacy_read_scoring_mutant_fails_cap_kill_pin(
    tmp_path, monkeypatch, shape
):
    _g1_mutant_legacy_branch_scoring_advance(monkeypatch)
    with pytest.raises(AssertionError):
        _assert_cap_kill_pins(tmp_path, monkeypatch, channel="legacy", shape=shape)


def _r1a_past_absolute_cap_if_false(monkeypatch) -> None:
    monkeypatch.setattr(g._TickWatch, "past_absolute_cap", lambda self, now: False)


def _r1b_cap_branch_not_hung(monkeypatch) -> None:
    """Mutant: cap exceeded but probe-unknown branch always ``continue`` (never strikes)."""
    orig = g._TickWatch.past_absolute_cap

    def _never_cap_for_unknown(self, now: float) -> bool:
        if self.probe_unknown or self.token is g._PROBE_UNKNOWN:
            return False
        return orig(self, now)

    monkeypatch.setattr(g._TickWatch, "past_absolute_cap", _never_cap_for_unknown)


def _r1c_age_none_clears_strikes_during_cap(monkeypatch) -> None:
    """Distinct from R1b: ``age is None`` clears strikes each tick (never reaches cap kill)."""
    monkeypatch.setattr(g, "_snapshot_age_seconds", lambda: None)


@pytest.mark.parametrize(
    "mutator",
    [
        _r1a_past_absolute_cap_if_false,
        _r1b_cap_branch_not_hung,
        _r1c_age_none_clears_strikes_during_cap,
    ],
    ids=["R1a-cap-if-false", "R1b-cap-branch-not-hung", "R1c-age-none-clears-strikes"],
)
def test_r18_1_mutations_fail_cap_kill_pin(tmp_path, monkeypatch, mutator):
    mutator(monkeypatch)
    with pytest.raises(AssertionError):
        _assert_cap_kill_pins(tmp_path, monkeypatch, channel="new", shape="null")
