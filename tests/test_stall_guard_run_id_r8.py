"""PR #1485 R8: run_id guard regressions, tick_body integration, mutation guards."""

from __future__ import annotations

import json
import os
import uuid
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


def test_s13_first_run_id_uses_fresh_watch_with_window_cap_anchor():
    """S13: do not adopt run_id via observe(); inherit window first_seen when id was unknown."""
    prior = g._TickWatch((None, "1/128"), 1000.0)
    after = g._watch_active_tick(prior, ("run-a", "2/128"), 1500.0)
    assert after is not prior
    assert after.run_id == "run-a"
    assert after.first_seen == 1000.0


def test_s2_clobbered_token_after_probe_unknown_keeps_same_run_cap(
    tmp_path, monkeypatch
):
    """S2: (None, progress) after outage with known watch.run_id is still the same run."""
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


def test_s1_late_first_run_id_after_unknown_window_hits_cap_from_window_start(
    tmp_path, monkeypatch
):
    """S1/S1b: identity first seen only after unknown still bounded by unknown-window start."""
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
        return g.TickProgressSnapshot(
            {"token": ("late-run", f"{step}/128")}, True
        )

    monkeypatch.setattr(g, "_tick_progress", _controlled)
    cap_ticks = int(g.tick_max_seconds() // g.INTERVAL_SECONDS)
    code, _ = _run_guard(
        monkeypatch, ticks=fail_checks + cap_ticks + g.CONSECUTIVE_CHECKS
    )
    assert code == 1


def test_first_run_after_unknown_short_post_window_not_killed_early(
    tmp_path, monkeypatch
):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    _old_receipt(6001)
    fail_checks = 4
    calls = {"n": 0}

    def _controlled():
        calls["n"] += 1
        if calls["n"] <= fail_checks:
            return g.TickProgressSnapshot(None, False)
        step = calls["n"] - fail_checks
        return g.TickProgressSnapshot(
            {"token": ("brand-new-run", f"{step}/128")}, True
        )

    monkeypatch.setattr(g, "_tick_progress", _controlled)
    code, _ = _run_guard(monkeypatch, ticks=fail_checks + 4)
    assert code is None


def test_tick_body_progress_writes_share_run_id_and_heartbeat_moves(
    tmp_path, monkeypatch
):
    from internal.council.scheduler_cycle_state import scheduler_state_path

    REAL_WEIGHTS = {
        "adversarial_state": {
            "council_weights": {"quant": 1.2, "hype": 0.9, "dark_horse": 1.0, "technical": 1.1}
        }
    }
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps(REAL_WEIGHTS))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    vol = tmp_path / "score_snapshots.json"
    vol.write_text("{}")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(vol))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))

    records: list = []
    real_write = snaps.ScoreSnapshotScheduler._persist_cycle_summary

    def _capture(self, result):
        records.append(dict(result))
        return real_write(self, result)

    heartbeats: list = []

    def _fake_universe(*, progress_cb=None, **_kw):
        if progress_cb:
            for step in (1, 2, 3):
                progress_cb(step, 10)
        return {"ok": True, "published": True, "count": 1, "path": str(vol)}

    monkeypatch.setattr(
        snaps.ScoreSnapshotScheduler, "_persist_cycle_summary", _capture
    )
    monkeypatch.setattr(snaps, "write_full_universe_snapshot", _fake_universe)

    sched = snaps.ScoreSnapshotScheduler()
    sched._tick_body(reschedule=False)

    scoring = [r for r in records if r.get("phase") == "scoring"]
    assert len(scoring) >= 4
    run_ids = {r["run_id"] for r in scoring if r.get("run_id")}
    assert len(run_ids) == 1
    run_at_values = [r["run_at"] for r in scoring if r.get("run_at")]
    assert len(set(run_at_values)) >= 2
    final = records[-1]
    assert final.get("phase") != "scoring"
    assert Path(scheduler_state_path()).exists()


# --- Mutation guards (must fail when mutation simulates writer bugs) ---


def _apply_m1_drop_run_id_from_progress(monkeypatch) -> None:
    from internal.council import scheduler_cycle_state as scs

    real = scs.write_last_cycle

    def _strip(summary, soul_map_path=None):
        payload = dict(summary)
        if payload.get("phase") == "scoring" and payload.get("progress"):
            payload.pop("run_id", None)
        return real(payload, soul_map_path)

    monkeypatch.setattr(scs, "write_last_cycle", _strip)


def _apply_m2_drop_run_id_from_tick_start(monkeypatch) -> None:
    from internal.council import scheduler_cycle_state as scs

    real = scs.write_last_cycle
    seen = {"n": 0}

    def _strip(summary, soul_map_path=None):
        payload = dict(summary)
        if payload.get("phase") == "scoring":
            seen["n"] += 1
            if seen["n"] == 1 and not payload.get("progress"):
                payload.pop("run_id", None)
        return real(payload, soul_map_path)

    monkeypatch.setattr(scs, "write_last_cycle", _strip)


def _apply_m3_constant_run_id(monkeypatch) -> None:
    fixed = f"constant-{uuid.uuid4().hex}"

    class _FixedUUID:
        @property
        def hex(self):
            return fixed

    monkeypatch.setattr(uuid, "uuid4", lambda: _FixedUUID())


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


def test_tick_body_distinct_run_id_per_scheduler_tick(tmp_path, monkeypatch):
    REAL_WEIGHTS = {
        "adversarial_state": {
            "council_weights": {"quant": 1.2, "hype": 0.9, "dark_horse": 1.0, "technical": 1.1}
        }
    }
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps(REAL_WEIGHTS))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    vol = tmp_path / "score_snapshots.json"
    vol.write_text("{}")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(vol))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    monkeypatch.setattr(
        snaps,
        "write_full_universe_snapshot",
        lambda **kw: {"ok": True, "published": True, "count": 1},
    )
    tick_run_ids: list = []
    real = snaps.ScoreSnapshotScheduler._persist_cycle_summary

    def _capture(self, result):
        if result.get("phase") == "scoring" and result.get("run_id") and result.get("progress") == "1/10":
            tick_run_ids.append(result["run_id"])
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
    assert len(tick_run_ids) == 2
    assert tick_run_ids[0] != tick_run_ids[1]


@pytest.mark.skipif(os.environ.get("PR1485_MUTATION") != "1", reason="mutation job only")
def test_m1_mutation_progress_records_must_include_run_id(tmp_path, monkeypatch):
    _apply_m1_drop_run_id_from_progress(monkeypatch)
    records = _tick_body_scoring_records(tmp_path, monkeypatch)
    progress_rows = [r for r in records if r.get("phase") == "scoring" and r.get("progress")]
    assert progress_rows
    assert all(r.get("run_id") for r in progress_rows)


@pytest.mark.skipif(os.environ.get("PR1485_MUTATION") != "1", reason="mutation job only")
def test_m2_mutation_tick_start_must_include_run_id(tmp_path, monkeypatch):
    _apply_m2_drop_run_id_from_tick_start(monkeypatch)
    records = _tick_body_scoring_records(tmp_path, monkeypatch)
    start_row = next(r for r in records if r.get("phase") == "scoring" and not r.get("progress"))
    assert start_row.get("run_id")


def _tick_body_scoring_records(tmp_path, monkeypatch) -> list:
    REAL_WEIGHTS = {
        "adversarial_state": {
            "council_weights": {"quant": 1.2, "hype": 0.9, "dark_horse": 1.0, "technical": 1.1}
        }
    }
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps(REAL_WEIGHTS))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    vol = tmp_path / "score_snapshots.json"
    vol.write_text("{}")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(vol))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
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
            [progress_cb(i, 10) for i in (1, 2, 3)] if progress_cb else None,
            {"ok": True, "published": True, "count": 1},
        )[1],
    )
    snaps.ScoreSnapshotScheduler()._tick_body(reschedule=False)
    return records


@pytest.mark.skipif(
    os.environ.get("PR1485_MUTATION") != "1",
    reason="Set PR1485_MUTATION=1 to verify writer mutations break the guard",
)
def test_m3_constant_run_id_across_ticks_fails_integration(tmp_path, monkeypatch):
    _apply_m3_constant_run_id(monkeypatch)
    REAL_WEIGHTS = {
        "adversarial_state": {
            "council_weights": {"quant": 1.2, "hype": 0.9, "dark_horse": 1.0, "technical": 1.1}
        }
    }
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps(REAL_WEIGHTS))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    vol = tmp_path / "score_snapshots.json"
    vol.write_text("{}")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(vol))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    tick_run_ids: list = []
    real = snaps.ScoreSnapshotScheduler._persist_cycle_summary

    def _capture(self, result):
        if result.get("phase") == "scoring" and result.get("run_id") and result.get("progress") == "1/10":
            tick_run_ids.append(result["run_id"])
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
    assert len(tick_run_ids) == 2
    assert tick_run_ids[0] == tick_run_ids[1]
