"""PR #1485 R9: fresh cap on first run_id; A1/A5/S13; writer invariants."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from internal import loop_stall_guard as g
from internal.council import score_snapshots as snaps
from internal.council import weights
from tests.test_stall_guard_missing_receipt_wedge import (
    _active_tick,
    _old_receipt,
    _run_guard,
    _scoring_progress,
    _wire,
)

REAL_WEIGHTS = {
    "adversarial_state": {
        "council_weights": {"quant": 1.2, "hype": 0.9, "dark_horse": 1.0, "technical": 1.1}
    }
}


def _tick_body_env(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps(REAL_WEIGHTS))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    vol = tmp_path / "score_snapshots.json"
    vol.write_text("{}")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(vol))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    return soul, vol


def test_s13_first_run_id_gets_fresh_watch_not_observe_adopt():
    prior = g._TickWatch((None, "1/128"), 1000.0)
    after = g._watch_active_tick(prior, ("run-b", "2/128"), 1500.0)
    assert after is not prior
    assert after.run_id == "run-b"
    assert after.first_seen == 1500.0


def test_a1_healthy_run_after_probe_unknown_window_not_killed_at_five_checks_old(
    tmp_path, monkeypatch
):
    """A1: six probe-unknown checks, then healthy B — must keep full cap runway."""
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    _old_receipt(6001)
    fail_checks = 6
    calls = {"n": 0}

    def _controlled():
        calls["n"] += 1
        if calls["n"] <= fail_checks:
            return g.TickProgressSnapshot(None, False)
        step = calls["n"] - fail_checks
        return g.TickProgressSnapshot({"token": ("run-b", f"{step}/128")}, True)

    monkeypatch.setattr(g, "_tick_progress", _controlled)
    code, _ = _run_guard(monkeypatch, ticks=fail_checks + 5)
    assert code is None


def test_a5_healthy_run_after_age_none_gap_not_killed_while_young(tmp_path, monkeypatch):
    """A5: one probe-unknown, twenty age-None checks, then healthy B (~12m mono is safe)."""
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    _old_receipt(6001)
    calls = {"n": 0}

    def _tick():
        calls["n"] += 1
        n = calls["n"]
        if n == 1:
            return g.TickProgressSnapshot(None, False)
        if n <= 21:
            return g.TickProgressSnapshot(None, True)
        step = n - 21
        return g.TickProgressSnapshot({"token": ("run-b", f"{step}/128")}, True)

    def _age():
        if 2 <= calls["n"] <= 21:
            return None
        return float(g.MAX_SNAPSHOT_AGE_SECONDS + 1)

    monkeypatch.setattr(g, "_tick_progress", _tick)
    monkeypatch.setattr(g, "_snapshot_age_seconds", _age)
    code, _ = _run_guard(monkeypatch, ticks=21 + 3)
    assert code is None


def test_s13_guard_healthy_run_not_killed_at_seven_checks(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    _old_receipt(6001)
    calls = {"n": 0}

    def _controlled():
        calls["n"] += 1
        if calls["n"] == 1:
            return g.TickProgressSnapshot({"token": (None, "0/128")}, True)
        if calls["n"] <= 7:
            return g.TickProgressSnapshot({"token": (None, f"{calls['n']}/128")}, True)
        step = calls["n"] - 7
        return g.TickProgressSnapshot({"token": ("run-b", f"{step}/128")}, True)

    monkeypatch.setattr(g, "_tick_progress", _controlled)
    code, _ = _run_guard(monkeypatch, ticks=7 + 6)
    assert code is None


def test_fresh_cap_after_probe_unknown_identity_less_window(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    _old_receipt(6001)
    fail_checks = 7
    calls = {"n": 0}

    def _controlled():
        calls["n"] += 1
        if calls["n"] <= fail_checks:
            return g.TickProgressSnapshot(None, False)
        step = calls["n"] - fail_checks
        return g.TickProgressSnapshot({"token": ("new-run", f"{step}/128")}, True)

    monkeypatch.setattr(g, "_tick_progress", _controlled)
    code, _ = _run_guard(monkeypatch, ticks=fail_checks + 6)
    assert code is None


def test_fresh_cap_after_age_none_identity_less_window(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    _old_receipt(6001)
    calls = {"n": 0}

    def _tick():
        calls["n"] += 1
        if calls["n"] <= 5:
            return g.TickProgressSnapshot(None, False)
        if calls["n"] <= 8:
            return g.TickProgressSnapshot(None, True)
        step = calls["n"] - 8
        return g.TickProgressSnapshot({"token": ("after-none", f"{step}/128")}, True)

    def _age():
        if 6 <= calls["n"] <= 8:
            return None
        return float(g.MAX_SNAPSHOT_AGE_SECONDS + 1)

    monkeypatch.setattr(g, "_tick_progress", _tick)
    monkeypatch.setattr(g, "_snapshot_age_seconds", _age)
    code, _ = _run_guard(monkeypatch, ticks=8 + 5)
    assert code is None


def test_hung_late_run_id_worst_case_numeric_bound(tmp_path, monkeypatch):
    """Default TICK_MAX_BASE=1200 → cap 1800s after first late run_id sight."""
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    _old_receipt(6001)
    fail_checks = 7
    cap_ticks = int(g.tick_max_seconds() // g.INTERVAL_SECONDS)
    strikes = g.CONSECUTIVE_CHECKS
    first_progress_tick = fail_checks + 1
    kill_at = first_progress_tick + cap_ticks + strikes
    calls = {"n": 0}

    def _controlled():
        calls["n"] += 1
        if calls["n"] <= fail_checks:
            return g.TickProgressSnapshot(None, False)
        step = calls["n"] - fail_checks
        return g.TickProgressSnapshot({"token": ("late-hung", f"{step}/128")}, True)

    monkeypatch.setattr(g, "_tick_progress", _controlled)
    code_survive, _ = _run_guard(monkeypatch, ticks=first_progress_tick + cap_ticks - 1)
    assert code_survive is None
    calls["n"] = 0
    code_kill, _ = _run_guard(monkeypatch, ticks=kill_at)
    assert code_kill == 1


def test_repeated_probe_unknown_same_run_does_not_reset_cap(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    _old_receipt(6001)
    run_id = "same-through-outages"
    calls = {"n": 0}

    def _controlled():
        calls["n"] += 1
        n = calls["n"]
        if n == 1:
            return g.TickProgressSnapshot({"token": (run_id, "1/128")}, True)
        if 2 <= n <= 4:
            return g.TickProgressSnapshot(None, False)
        if 5 <= n <= 7:
            step = n - 4
            return g.TickProgressSnapshot({"token": (run_id, f"{step}/128")}, True)
        if 8 <= n <= 10:
            return g.TickProgressSnapshot(None, False)
        step = n - 10
        return g.TickProgressSnapshot({"token": (run_id, f"{step}/128")}, True)

    monkeypatch.setattr(g, "_tick_progress", _controlled)
    cap_ticks = int(g.tick_max_seconds() // g.INTERVAL_SECONDS)
    code, _ = _run_guard(monkeypatch, ticks=8)
    assert code is None
    code, _ = _run_guard(
        monkeypatch, ticks=10 + cap_ticks + g.CONSECUTIVE_CHECKS + 2
    )
    assert code == 1


def test_clear_stuck_scoring_persist_carries_run_id(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from internal.council.scheduler_cycle_state import read_last_cycle, write_last_cycle

    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps(REAL_WEIGHTS))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_last_cycle(
        {
            "run_id": "stuck-run-id",
            "run_at": old,
            "ok": False,
            "phase": "scoring",
            "progress": "1/128",
        }
    )
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_STUCK_SECONDS", 60)
    snaps.ScoreSnapshotScheduler()._clear_stuck_scoring()
    last = read_last_cycle()
    assert last.get("run_id") == "stuck-run-id"
    assert last.get("error") == "scoring_stuck_timeout"


def test_s2_clobbered_token_after_probe_unknown_keeps_same_run_cap(
    tmp_path, monkeypatch
):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    _old_receipt(6001)
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

    monkeypatch.setattr(g, "_tick_progress", _controlled)
    cap_ticks = int(g.tick_max_seconds() // g.INTERVAL_SECONDS)
    code, _ = _run_guard(monkeypatch, ticks=6 + cap_ticks + g.CONSECUTIVE_CHECKS + 2)
    assert code == 1


def _tick_body_records(tmp_path, monkeypatch, *, progress_steps=(1, 2, 3)):
    _tick_body_env(tmp_path, monkeypatch)
    records: list = []
    real = snaps.ScoreSnapshotScheduler._persist_cycle_summary

    def _capture(self, result):
        records.append(dict(result))
        return real(self, result)

    monkeypatch.setattr(snaps.ScoreSnapshotScheduler, "_persist_cycle_summary", _capture)
    monkeypatch.setattr(
        snaps,
        "write_full_universe_snapshot",
        lambda progress_cb=None, **kw: (
            [progress_cb(i, 10) for i in progress_steps] if progress_cb else None,
            {"ok": True, "published": True, "count": 1, "path": str(tmp_path / "score_snapshots.json")},
        )[1],
    )
    snaps.ScoreSnapshotScheduler()._tick_body(reschedule=False)
    return records


def test_tick_body_every_scoring_row_includes_run_id(tmp_path, monkeypatch):
    from internal.council.scheduler_cycle_state import scheduler_state_path

    records = _tick_body_records(tmp_path, monkeypatch)
    scoring = [r for r in records if r.get("phase") == "scoring"]
    assert len(scoring) >= 4
    assert all(r.get("run_id") for r in scoring)
    run_ids = {r["run_id"] for r in scoring}
    assert len(run_ids) == 1
    run_at_values = [r["run_at"] for r in scoring if r.get("run_at")]
    assert len(set(run_at_values)) >= 2
    assert records[-1].get("phase") != "scoring"
    assert Path(scheduler_state_path()).exists()


def test_tick_body_tick_start_record_includes_run_id(tmp_path, monkeypatch):
    records = _tick_body_records(tmp_path, monkeypatch)
    start = next(r for r in records if r.get("phase") == "scoring" and not r.get("progress"))
    assert start.get("run_id")


def test_tick_body_distinct_run_id_per_scheduler_tick(tmp_path, monkeypatch):
    _tick_body_env(tmp_path, monkeypatch)
    ids: list = []
    real = snaps.ScoreSnapshotScheduler._persist_cycle_summary

    def _capture(self, result):
        if result.get("phase") == "scoring" and result.get("progress") == "1/10":
            ids.append(result.get("run_id"))
        return real(self, result)

    monkeypatch.setattr(snaps.ScoreSnapshotScheduler, "_persist_cycle_summary", _capture)
    monkeypatch.setattr(
        snaps,
        "write_full_universe_snapshot",
        lambda progress_cb=None, **kw: (
            progress_cb(1, 10) if progress_cb else None,
            {"ok": True, "published": True, "count": 1},
        )[1],
    )
    sched = snaps.ScoreSnapshotScheduler()
    sched._tick_body(reschedule=False)
    sched._tick_body(reschedule=False)
    assert len(ids) == 2
    assert ids[0] and ids[1] and ids[0] != ids[1]


def _same_run_cap_scenario(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    _old_receipt(6001)
    _active_tick(monkeypatch)
    run_id = _scoring_progress(1)
    fail_checks = 6
    calls = {"n": 0}
    real = g._tick_progress

    def _flaky():
        calls["n"] += 1
        if calls["n"] <= fail_checks:
            return g.TickProgressSnapshot(None, False)
        _scoring_progress(calls["n"] - fail_checks, run_id=run_id)
        return real()

    monkeypatch.setattr(g, "_tick_progress", _flaky)
    cap_ticks = int(g.tick_max_seconds() // g.INTERVAL_SECONDS)
    return _run_guard(
        monkeypatch, ticks=fail_checks + cap_ticks + g.CONSECUTIVE_CHECKS + 2
    )


def test_same_run_real_writer_reaches_cap_after_probe_outage(tmp_path, monkeypatch):
    code, _ = _same_run_cap_scenario(tmp_path, monkeypatch)
    assert code == 1


def _apply_m1_drop_run_id_from_progress(monkeypatch) -> None:
    from internal.council import scheduler_cycle_state as scs

    real = scs.write_last_cycle

    def _strip(summary, soul_map_path=None):
        payload = dict(summary)
        if payload.get("phase") == "scoring" and payload.get("progress"):
            payload.pop("run_id", None)
        return real(payload, soul_map_path)

    monkeypatch.setattr(scs, "write_last_cycle", _strip)


@pytest.mark.skipif(os.environ.get("PR1485_MUTATION") != "1", reason="mutation job only")
def test_m1_mutation_progress_records_must_include_run_id(tmp_path, monkeypatch):
    _apply_m1_drop_run_id_from_progress(monkeypatch)
    records = _tick_body_records(tmp_path, monkeypatch)
    progress_rows = [r for r in records if r.get("phase") == "scoring" and r.get("progress")]
    assert progress_rows
    assert all(r.get("run_id") for r in progress_rows)
