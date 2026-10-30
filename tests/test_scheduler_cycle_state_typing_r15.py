"""PR #1485 R15: last_cycle field typing + M8c top-level non-object."""

from __future__ import annotations

import json

import pytest

from internal import loop_stall_guard as g
from internal.council import scheduler_cycle_state as scs
from internal.council import score_snapshots as snaps
from internal.council import weights
from internal.council.scheduler_cycle_state import (
    CycleStateUnreadableError,
    read_last_cycle_with_status,
)


def _wire_paths(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    state = tmp_path / "score_snapshot_scheduler.json"
    monkeypatch.setenv("SCORE_SNAPSHOT_SCHEDULER_STATE_PATH", str(state))
    return soul, state


def _assert_unreadable_probe_unknown(monkeypatch) -> None:
    monkeypatch.setattr(snaps, "_TICK_ACTIVE", True)
    _summary, status = read_last_cycle_with_status()
    assert status == "unreadable"
    with pytest.raises(CycleStateUnreadableError):
        snaps.producer_tick_progress()


@pytest.mark.parametrize(
    "last_cycle",
    [
        {"phase": None, "run_id": "r", "progress": "1/9"},
        {"phase": 5, "run_id": "r", "progress": "1/9"},
        {"phase": ["scoring"], "run_id": "r"},
        {"phase": True, "run_id": "r"},
        {"phase": {}, "run_id": "r"},
        {"phase": "scoring", "run_id": 1, "progress": "1/9"},
        {"phase": "scoring", "run_id": "r", "progress": ["1/9"]},
    ],
    ids=[
        "phase-null",
        "phase-int",
        "phase-list",
        "phase-bool",
        "phase-object",
        "run_id-int",
        "progress-list",
    ],
)
def test_new_file_bad_last_cycle_field_types_unreadable(
    tmp_path, monkeypatch, last_cycle
):
    _, state = _wire_paths(tmp_path, monkeypatch)
    state.write_text(json.dumps({"last_cycle": last_cycle}), encoding="utf-8")
    _assert_unreadable_probe_unknown(monkeypatch)


@pytest.mark.parametrize(
    "last_cycle",
    [
        {"phase": None, "run_id": "r", "progress": "1/9"},
        {"phase": 5, "run_id": "r", "progress": "1/9"},
        {"phase": "scoring", "run_id": 99},
    ],
    ids=["phase-null", "phase-int", "run_id-int"],
)
def test_legacy_bad_last_cycle_field_types_unreadable(
    tmp_path, monkeypatch, last_cycle
):
    soul, _ = _wire_paths(tmp_path, monkeypatch)
    soul.write_text(
        json.dumps({"score_snapshot_scheduler": {"last_cycle": last_cycle}}),
        encoding="utf-8",
    )
    _assert_unreadable_probe_unknown(monkeypatch)


def test_null_run_id_in_last_cycle_still_ok_for_reader(tmp_path, monkeypatch):
    _, state = _wire_paths(tmp_path, monkeypatch)
    state.write_text(
        json.dumps({"last_cycle": {"phase": "scoring", "run_id": None, "progress": "1/9"}}),
        encoding="utf-8",
    )
    summary, status = read_last_cycle_with_status()
    assert status == "ok"
    assert summary.get("run_id") is None
    monkeypatch.setattr(snaps, "_TICK_ACTIVE", True)
    assert snaps.producer_tick_progress() == {"token": (None, "1/9")}


def test_empty_last_cycle_object_unreadable_new_and_legacy(tmp_path, monkeypatch):
    """Empty ``{}`` last_cycle is unreadable on both readers (aligned rule)."""
    soul, state = _wire_paths(tmp_path, monkeypatch)
    state.write_text(json.dumps({"last_cycle": {}}), encoding="utf-8")
    _assert_unreadable_probe_unknown(monkeypatch)

    soul.write_text(
        json.dumps({"score_snapshot_scheduler": {"last_cycle": {}}}),
        encoding="utf-8",
    )
    state.write_text("{}", encoding="utf-8")
    _assert_unreadable_probe_unknown(monkeypatch)


@pytest.mark.parametrize(
    "raw",
    ["[]", "null", '"string-root"', "42"],
    ids=["array", "null", "string", "number"],
)
def test_new_file_top_level_non_object_is_unreadable(tmp_path, monkeypatch, raw):
    _, state = _wire_paths(tmp_path, monkeypatch)
    state.write_text(raw, encoding="utf-8")
    _summary, status = read_last_cycle_with_status()
    assert status == "unreadable"
    assert status != "missing"


@pytest.mark.parametrize(
    "payload",
    [[], None, "bad", 7],
    ids=["array", "null", "string", "number"],
)
def test_legacy_top_level_non_object_is_unreadable(tmp_path, monkeypatch, payload):
    soul, _ = _wire_paths(tmp_path, monkeypatch)
    soul.write_text(json.dumps(payload), encoding="utf-8")
    _summary, status = read_last_cycle_with_status()
    assert status == "unreadable"
    assert status != "missing"


def test_m8c_new_root_mutant_returning_missing_would_fail_unreadable_tests(
    tmp_path, monkeypatch
):
    """Simulated ``return None, False`` on non-object root → missing (must not ship)."""
    _, state = _wire_paths(tmp_path, monkeypatch)
    state.write_text("[]", encoding="utf-8")
    real = scs._read_new

    def _mutant(soul_map_path=None):
        path = scs.scheduler_state_path(soul_map_path)
        try:
            raw = open(path, encoding="utf-8").read()
        except FileNotFoundError:
            return None, False
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None, False
        return real(soul_map_path)

    monkeypatch.setattr(scs, "_read_new", _mutant)
    assert read_last_cycle_with_status()[1] == "missing"


def test_m8c_legacy_root_mutant_returning_missing_would_fail_unreadable_tests(
    tmp_path, monkeypatch
):
    soul, _ = _wire_paths(tmp_path, monkeypatch)
    soul.write_text("[]", encoding="utf-8")
    real = scs._read_legacy_with_status

    def _mutant(soul_map_path=None):
        path = scs._soul_path(soul_map_path)
        try:
            raw = open(path, encoding="utf-8").read()
        except FileNotFoundError:
            return {}, False
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}, False
        return real(soul_map_path)

    monkeypatch.setattr(scs, "_read_legacy_with_status", _mutant)
    assert read_last_cycle_with_status()[1] == "missing"


def _frozen_token_flap_run(monkeypatch, tmp_path, *, outage_every: int, ticks: int):
    from tests.test_stall_guard_run_id_r12 import _flapping_hung_none_none_ticks

    return _flapping_hung_none_none_ticks(
        outage_every=outage_every, ticks=ticks, monkeypatch=monkeypatch, tmp_path=tmp_path
    )


@pytest.mark.parametrize(
    ("outage_every", "kill_at"),
    [(3, 9), (4, 7)],
)
def test_frozen_identity_less_token_flap_exits_at_no_progress_deadline(
    tmp_path, monkeypatch, outage_every, kill_at
):
    """Fails on 1ada719b: unconditional ``last_progress`` refresh delayed kill to ~check 11+."""
    code, _ = _frozen_token_flap_run(monkeypatch, tmp_path, outage_every=outage_every, ticks=kill_at)
    assert code == 1
    code_survive, _ = _frozen_token_flap_run(
        monkeypatch, tmp_path, outage_every=outage_every, ticks=kill_at - 1
    )
    assert code_survive is None


def test_unconditional_last_progress_on_resume_fails_frozen_flap_test(
    tmp_path, monkeypatch
):
    real = g._watch_active_tick

    def _old_resume_always_refreshes_progress(watch, token, now):
        if watch is not None and watch.probe_unknown and g._tokens_same_run(watch, token):
            watch.probe_unknown = False
            watch.token = token
            watch.last_progress = now
            resumed = g._token_run_id(token)
            if resumed is not None:
                watch.run_id = resumed
            return watch
        return real(watch, token, now)

    monkeypatch.setattr(g, "_watch_active_tick", _old_resume_always_refreshes_progress)
    code, _ = _frozen_token_flap_run(monkeypatch, tmp_path, outage_every=3, ticks=9)
    assert code is None
    code, _ = _frozen_token_flap_run(monkeypatch, tmp_path, outage_every=3, ticks=11)
    assert code == 1
