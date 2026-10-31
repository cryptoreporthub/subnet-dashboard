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


def _install_probe_unknown_path_spy(monkeypatch) -> list[str]:
    """Record guard-loop probe-unknown signals (R21: not kill timing alone)."""
    events: list[str] = []
    real_init = g._TickWatch.__init__

    def _init_spy(self, token, now, *, probe_unknown=False):
        if probe_unknown or token is g._PROBE_UNKNOWN:
            events.append("probe_unknown_watch")
        return real_init(self, token, now, probe_unknown=probe_unknown)

    real_progress = g._tick_progress

    def _progress_spy():
        snap = real_progress()
        if not snap.probe_ok:
            events.append("tick_progress_probe_failed")
        return snap

    monkeypatch.setattr(g._TickWatch, "__init__", _init_spy)
    monkeypatch.setattr(g, "_tick_progress", _progress_spy)
    return events


def _assert_probe_unknown_path_taken(events: list[str], *, checks: int, label: str) -> None:
    """R22: the guard must read **every** stale check as probe-unknown (exact count).

    ``checks`` is the number of guard checks that ran in this window (each one is stale: the
    receipt is old and the tick is active). A reader that is probe-unknown only on some checks,
    or never, changes the count even when the kill still lands at the same check.
    """
    failed = events.count("tick_progress_probe_failed")
    assert failed == checks, (
        f"expected probe-unknown on every stale check ({label}): "
        f"{failed} of {checks}; spy={events!r}"
    )


def _assert_cap_kill_pins(tmp_path, monkeypatch, *, channel: str, shape: str) -> None:
    _wire(tmp_path, monkeypatch)
    _scheduler_state_path(tmp_path, monkeypatch)
    _seed_disk(tmp_path, monkeypatch, channel=channel, shape=shape)
    if channel == "legacy":
        _assert_legacy_cycle_read_ok(shape=shape)
    kill_at = _guard_defaults(monkeypatch)
    monkeypatch.setattr(snaps, "_TICK_ACTIVE", True)
    _old_receipt(6001)
    probe_spy = _install_probe_unknown_path_spy(monkeypatch)
    label = f"{channel}/{shape}"
    code_survive, _ = _run_guard(monkeypatch, ticks=kill_at - 1)
    _assert_probe_unknown_path_taken(probe_spy, checks=kill_at - 1, label=label)
    assert code_survive is None
    probe_spy.clear()
    code_kill, _ = _run_guard(monkeypatch, ticks=kill_at)
    _assert_probe_unknown_path_taken(probe_spy, checks=kill_at, label=label)
    assert code_kill == 1


@pytest.mark.parametrize("channel", ["new", "legacy"])
@pytest.mark.parametrize("shape", ["null", "absent", "failed", "missing"])
def test_null_phase_stale_disk_cap_kill_pins(
    tmp_path, monkeypatch, channel, shape
):
    """Real ``_guard_loop`` via ``_run_guard``: exit at cap + ``CONSECUTIVE_CHECKS``, not before."""
    _assert_cap_kill_pins(tmp_path, monkeypatch, channel=channel, shape=shape)


def _g1_mutant_legacy_branch_scoring_frozen(monkeypatch) -> None:
    """Legacy read returns **fixed** ``64/128`` scoring (active tick, not probe-unknown)."""
    import internal.council.scheduler_cycle_state as cycle_state

    real = cycle_state._read_legacy_with_status

    def _frozen_scoring_legacy(soul_map_path=None):
        summary, unreadable = real(soul_map_path)
        if unreadable or not summary:
            return summary, unreadable
        return (
            {
                **summary,
                "phase": "scoring",
                "progress": "64/128",
                "run_id": "legacy-mutant-frozen",
                "ok": False,
            },
            False,
        )

    monkeypatch.setattr(cycle_state, "_read_legacy_with_status", _frozen_scoring_legacy)


def _g1_mutant_legacy_branch_scoring_advancing(monkeypatch) -> None:
    """Legacy read returns scoring with **advancing** progress each call (not probe-unknown)."""
    import internal.council.scheduler_cycle_state as cycle_state

    real = cycle_state._read_legacy_with_status
    state = {"n": 0}

    def _advancing_scoring_legacy(soul_map_path=None):
        summary, unreadable = real(soul_map_path)
        if unreadable or not summary:
            return summary, unreadable
        state["n"] += 1
        done = min(state["n"], 128)
        return (
            {
                **summary,
                "phase": "scoring",
                "progress": f"{done}/128",
                "run_id": "legacy-mutant-advancing",
                "ok": False,
            },
            False,
        )

    monkeypatch.setattr(cycle_state, "_read_legacy_with_status", _advancing_scoring_legacy)


@pytest.mark.parametrize("shape", ["null", "absent", "failed"])
def test_g1_legacy_frozen_scoring_mutant_fails_probe_unknown_path_pin(
    tmp_path, monkeypatch, shape
):
    _g1_mutant_legacy_branch_scoring_frozen(monkeypatch)
    with pytest.raises(AssertionError, match="expected probe-unknown on every stale check"):
        _assert_cap_kill_pins(tmp_path, monkeypatch, channel="legacy", shape=shape)


@pytest.mark.parametrize("shape", ["null", "absent", "failed"])
def test_g1_legacy_advancing_scoring_mutant_fails_probe_unknown_path_pin(
    tmp_path, monkeypatch, shape
):
    _g1_mutant_legacy_branch_scoring_advancing(monkeypatch)
    with pytest.raises(AssertionError, match="expected probe-unknown on every stale check"):
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


# --- R22: advancing / frozen / alternating readers in both channels, killed by the exact probe-unknown count.


def _scoring_reader_mutant(monkeypatch, *, channel: str, kind: str) -> None:
    """Replace the legacy or new reader so a stale null-phase record reads as in-flight scoring.

    ``kind``: ``frozen`` (fixed progress), ``advancing`` (progress increments on every read),
    ``alternating`` (frozen scoring on every other **guard check**, the real record otherwise;
    Claude #1533 6537526474 finding 1).
    """
    import internal.council.scheduler_cycle_state as cycle_state

    state = {"reads": 0, "checks": 0}

    def _scoring(summary: dict) -> dict:
        state["reads"] += 1
        if kind == "advancing":
            progress = f"{min(state['reads'], 128)}/128"
        else:
            progress = "64/128"
        return {**summary, "phase": "scoring", "progress": progress, "run_id": f"mutant-{kind}", "ok": False}

    def _active() -> bool:
        return kind != "alternating" or state["checks"] % 2 == 1

    if channel == "legacy":
        real_legacy = cycle_state._read_legacy_with_status

        def _legacy(soul_map_path=None):
            summary, unreadable = real_legacy(soul_map_path)
            if unreadable or not summary or not _active():
                return summary, unreadable
            return _scoring(summary), False

        monkeypatch.setattr(cycle_state, "_read_legacy_with_status", _legacy)
    else:
        real_new = cycle_state._read_new

        def _new(soul_map_path=None):
            summary, unreadable = real_new(soul_map_path)
            if unreadable or summary is None or not _active():
                return summary, unreadable
            return _scoring(summary), False

        monkeypatch.setattr(cycle_state, "_read_new", _new)

    if kind == "alternating":
        real_progress = g._tick_progress

        def _counted_progress():
            state["checks"] += 1
            return real_progress()

        monkeypatch.setattr(g, "_tick_progress", _counted_progress)


@pytest.mark.parametrize("kind", ["frozen", "advancing", "alternating"])
@pytest.mark.parametrize("shape", ["null", "absent", "failed"])
@pytest.mark.parametrize("channel", ["new", "legacy"])
def test_r22_scoring_reader_mutants_fail_probe_unknown_count_pin(
    tmp_path, monkeypatch, channel, shape, kind
):
    """Each mutant reads a stale record as scoring on some or all checks; the pin must fail on the count."""
    _scoring_reader_mutant(monkeypatch, channel=channel, kind=kind)
    with pytest.raises(AssertionError, match="expected probe-unknown on every stale check"):
        _assert_cap_kill_pins(tmp_path, monkeypatch, channel=channel, shape=shape)


def test_r22_probe_unknown_count_is_exact_per_window(tmp_path, monkeypatch):
    """The real guard reports one failed probe per stale check: 10 alive, then 11 up to the kill."""
    _wire(tmp_path, monkeypatch)
    _scheduler_state_path(tmp_path, monkeypatch)
    _seed_disk(tmp_path, monkeypatch, channel="new", shape="null")
    kill_at = _guard_defaults(monkeypatch)
    monkeypatch.setattr(snaps, "_TICK_ACTIVE", True)
    _old_receipt(6001)
    events = _install_probe_unknown_path_spy(monkeypatch)
    assert _run_guard(monkeypatch, ticks=kill_at - 1)[0] is None
    assert events.count("tick_progress_probe_failed") == kill_at - 1 == 10
    events.clear()
    assert _run_guard(monkeypatch, ticks=kill_at)[0] == 1
    assert events.count("tick_progress_probe_failed") == kill_at == 11
