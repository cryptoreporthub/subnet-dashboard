"""PR-C graft (MC design decision on #1479): a missing cycle receipt is a wedge
signal when the owner's servable snapshot is old, even with no volume file.

Drives the real ``_guard_loop`` against the real ``read_served_snapshot`` and the
real image seed. Only sleep, os._exit, revive and the resolver probe are stubbed.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from internal import loop_stall_guard as g
from internal.council import score_snapshots as snaps
from internal.learning import loop_health
from tests.score_snapshot_testutil import complete_snapshot_payload

REPO_SEED = str(Path(__file__).resolve().parents[1] / "data_seeds" / "score_snapshots.json")


class _Exit(Exception):
    def __init__(self, code):
        self.code = code


class _Stop(Exception):
    pass


def _aged_real_seed(tmp_path, *, age_seconds=8 * 86400) -> str:
    snap = json.loads(Path(REPO_SEED).read_text(encoding="utf-8"))
    stamp = datetime.fromtimestamp(time.time() - age_seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snap["written_at"] = snap["build_started_at"] = stamp
    out = tmp_path / "aged_seed.json"
    out.write_text(json.dumps(snap), encoding="utf-8")
    return str(out)


def _wire(tmp_path, monkeypatch, *, seed=None):
    seed = seed or _aged_real_seed(tmp_path)
    vol = tmp_path / "score_snapshots.json"
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(vol))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", seed)
    monkeypatch.setattr(loop_health, "SCORE_SNAPSHOTS_PATH", str(vol))
    monkeypatch.setattr(loop_health, "SOUL_MAP_PATH", str(soul), raising=False)
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    monkeypatch.delenv("SCORE_SNAPSHOT_CYCLE_PATH", raising=False)
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "essential")
    monkeypatch.delenv("STAGE2_HOP", raising=False)
    monkeypatch.delenv("SCORE_SNAPSHOT_SCHEDULER_ENABLED", raising=False)
    return vol


def _run_guard(
    monkeypatch, *, ticks=4, revive_writes_receipt=False, on_tick=None, revive=None, real_revive=False
):
    """Run the real guard loop for ``ticks`` ticks. Returns (exit_code, revives).

    The monotonic clock is fake: each tick advances it by the guard interval.
    ``on_tick(n)`` runs before the n-th check; ``revive`` replaces the revive stub.
    """
    revives = []

    def _revive():
        revives.append(1)
        if revive_writes_receipt:
            snaps.record_cycle_receipt({"complete": False}, outcome="incomplete")
        if revive is not None:
            return revive(len(revives))

    state = {"n": 0, "t": 1000.0}

    def _sleep(_s):
        state["n"] += 1
        state["t"] += g.INTERVAL_SECONDS
        if state["n"] > ticks:
            raise _Stop()
        if on_tick is not None:
            on_tick(state["n"])

    monkeypatch.setattr(g, "_now_mono", lambda: state["t"])

    def _exit(code):
        raise _Exit(code)

    monkeypatch.setattr(g, "ENABLED", True)
    monkeypatch.setattr(g, "KILL_ENABLED", True)
    monkeypatch.setattr(g, "BOOT_GRACE_SECONDS", 0)
    monkeypatch.setattr(g, "CONSECUTIVE_CHECKS", 3)
    monkeypatch.setattr(g, "MAX_SNAPSHOT_AGE_SECONDS", 5400)
    if not real_revive:
        monkeypatch.setattr(g, "_try_revive", _revive)
    monkeypatch.setattr(g, "_resolver_tick_age_seconds", lambda: None)
    monkeypatch.setattr(g.time, "sleep", _sleep)
    monkeypatch.setattr(g.os, "_exit", _exit)
    try:
        g._guard_loop()
    except _Exit as e:
        return e.code, len(revives)
    except _Stop:
        return None, len(revives)
    return "returned_idle", len(revives)


def _write_volume(vol: Path, *, age_seconds: float) -> None:
    ts = datetime.fromtimestamp(time.time() - age_seconds, tz=timezone.utc)
    vol.write_text(
        json.dumps(complete_snapshot_payload(written_at=ts.strftime("%Y-%m-%dT%H:%M:%SZ"))),
        encoding="utf-8",
    )


def test_premise_seed_is_servable_and_old_with_no_volume_file(tmp_path, monkeypatch):
    vol = _wire(tmp_path, monkeypatch)
    assert not vol.exists()
    served = snaps.read_served_snapshot()
    assert served.state is snaps.ServedState.SEED
    assert served.age_seconds > 5400
    assert snaps.producer_cycle_age_seconds() is None


def test_missing_receipt_and_old_seed_with_no_volume_file_is_a_wedge(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    code, revives = _run_guard(monkeypatch)
    assert revives == 1
    assert code == 1


def test_missing_receipt_wedge_self_heals_when_revive_writes_a_receipt(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    code, revives = _run_guard(monkeypatch, revive_writes_receipt=True)
    assert revives == 1
    assert code is None


def test_missing_receipt_and_nothing_servable_is_a_wedge(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, seed=str(tmp_path / "no_seed.json"))
    assert not snaps.read_served_snapshot().servable
    code, revives = _run_guard(monkeypatch)
    assert (code, revives) == (1, 1)


def test_missing_receipt_with_young_complete_volume_does_not_strike(tmp_path, monkeypatch):
    vol = _wire(tmp_path, monkeypatch)
    _write_volume(vol, age_seconds=60)
    code, revives = _run_guard(monkeypatch)
    assert (code, revives) == (None, 0)


def test_missing_receipt_is_not_masked_by_a_young_seed(tmp_path, monkeypatch):
    """Ditto: a young seed is a static artifact, not proof the producer ran."""
    young_seed = _aged_real_seed(tmp_path, age_seconds=60)
    vol = _wire(tmp_path, monkeypatch, seed=young_seed)
    assert not vol.exists()
    served = snaps.read_served_snapshot()
    assert served.origin == "seed" and served.age_seconds < 5400
    code, revives = _run_guard(monkeypatch)
    assert (code, revives) == (1, 1)


def test_young_seed_wedge_self_heals_when_revive_writes_a_receipt(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, seed=_aged_real_seed(tmp_path, age_seconds=60))
    code, revives = _run_guard(monkeypatch, revive_writes_receipt=True)
    assert (code, revives) == (None, 1)


def test_servable_volume_snapshot_of_unknown_age_never_revives_or_exits(tmp_path, monkeypatch):
    """Ditto: readers still have a snapshot, so an unknown age is not a stale one."""
    vol = _wire(tmp_path, monkeypatch)
    _write_volume(vol, age_seconds=60)
    real = snaps.read_served_snapshot()
    unknown = snaps.ServedSnapshot(real.state, real.snapshot, None, "volume", None)
    monkeypatch.setattr(snaps, "read_served_snapshot", lambda *a, **k: unknown)
    code, revives = _run_guard(monkeypatch, ticks=6)
    assert (code, revives) == (None, 0)


def test_future_dated_receipt_does_not_hide_a_wedged_producer(tmp_path, monkeypatch):
    """A receipt dated 30 days ahead must not read as fresh forever."""
    _wire(tmp_path, monkeypatch)
    snaps.record_cycle_receipt({"complete": False}, outcome="incomplete")
    path = Path(snaps._score_snapshot_cycle_path())
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["attempted_at"] = datetime.fromtimestamp(time.time() + 30 * 86400, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    path.write_text(json.dumps(receipt), encoding="utf-8")
    code, revives = _run_guard(monkeypatch)
    assert (code, revives) == (1, 1)


def test_future_dated_receipt_self_heals_when_revive_rewrites_the_receipt(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    snaps.record_cycle_receipt({"complete": False}, outcome="incomplete")
    path = Path(snaps._score_snapshot_cycle_path())
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["attempted_at"] = datetime.fromtimestamp(time.time() + 30 * 86400, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    path.write_text(json.dumps(receipt), encoding="utf-8")
    code, revives = _run_guard(monkeypatch, revive_writes_receipt=True)
    assert (code, revives) == (None, 1)


def _old_receipt(age_seconds: float) -> None:
    snaps.record_cycle_receipt({"complete": False}, outcome="published")
    path = Path(snaps._score_snapshot_cycle_path())
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["attempted_at"] = datetime.fromtimestamp(time.time() - age_seconds, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    path.write_text(json.dumps(receipt), encoding="utf-8")


def _scoring_progress(done: int, total: int = 128, run_at: str = "2026-10-29T00:00:00Z") -> None:
    from internal.council.scheduler_cycle_state import write_last_cycle

    write_last_cycle(
        {"run_at": run_at, "ok": False, "phase": "scoring", "progress": f"{done}/{total}"}
    )


def _active_tick(monkeypatch) -> None:
    monkeypatch.setattr(snaps, "_TICK_ACTIVE", True)


def test_premise_active_tick_is_visible_to_the_probe(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    assert snaps.producer_tick_progress() is None
    _active_tick(monkeypatch)
    _scoring_progress(3)
    assert snaps.producer_tick_progress() == {"token": ("2026-10-29T00:00:00Z", "3/128")}


def test_long_running_advancing_tick_with_an_old_receipt_is_never_killed(tmp_path, monkeypatch):
    """Replit P2: receipt 6001s old and _TICK_ACTIVE, but the scoring phase keeps advancing."""
    _wire(tmp_path, monkeypatch)
    _old_receipt(6001)
    _active_tick(monkeypatch)
    _scoring_progress(0)
    # 12 checks = 2880s of fake time: past the 900s progress deadline, inside the 3600s cap.
    assert 12 * g.INTERVAL_SECONDS < g.tick_max_seconds()
    code, revives = _run_guard(
        monkeypatch, ticks=12, on_tick=lambda n: _scoring_progress(n)
    )
    assert (code, revives) == (None, 0)


def test_hung_active_tick_with_no_progress_is_restarted_after_the_deadline(tmp_path, monkeypatch):
    """Not exempt forever: an active tick whose progress stopped still gets the restart."""
    _wire(tmp_path, monkeypatch)
    _old_receipt(6001)
    _active_tick(monkeypatch)
    _scoring_progress(5)
    code, revives = _run_guard(monkeypatch, ticks=20)
    assert code == 1
    assert revives >= 1


def test_hung_tick_is_not_killed_before_the_progress_deadline(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    _old_receipt(6001)
    _active_tick(monkeypatch)
    _scoring_progress(5)
    deadline_ticks = int(g.tick_progress_seconds() // g.INTERVAL_SECONDS)
    code, revives = _run_guard(monkeypatch, ticks=deadline_ticks)
    assert (code, revives) == (None, 0)


def test_no_progress_deadline_follows_the_schedulers_configured_threshold(tmp_path, monkeypatch):
    """Replit/Ditto: with SCORE_SNAPSHOT_STUCK_SECONDS=1800 the guard must not strike at 900."""
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_STUCK_SECONDS", 1800)
    assert g.tick_progress_seconds() == 1800
    _old_receipt(6001)
    _active_tick(monkeypatch)
    _scoring_progress(5)
    # Check k sees 240*(k-1)s of no progress: 8 checks reach 1680s, still inside 1800s.
    code, revives = _run_guard(monkeypatch, ticks=8)
    assert (code, revives) == (None, 0)


def test_no_progress_past_the_schedulers_threshold_is_restarted(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_STUCK_SECONDS", 1800)
    _old_receipt(6001)
    _active_tick(monkeypatch)
    _scoring_progress(5)
    code, revives = _run_guard(monkeypatch, ticks=20)
    assert code == 1
    assert revives >= 1


def test_guard_override_may_raise_but_never_undercut_the_scheduler_threshold(monkeypatch):
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_STUCK_SECONDS", 1800)
    monkeypatch.setattr(g, "TICK_PROGRESS_OVERRIDE_SECONDS", 300)
    monkeypatch.setattr(g, "_override_clamp_logged", False)
    assert g.tick_progress_seconds() == 1800
    monkeypatch.setattr(g, "TICK_PROGRESS_OVERRIDE_SECONDS", 2400)
    assert g.tick_progress_seconds() == 2400
    monkeypatch.setattr(g, "TICK_PROGRESS_OVERRIDE_SECONDS", 0)
    assert g.tick_progress_seconds() == 1800


def test_hard_cap_never_undercuts_the_progress_deadline(tmp_path, monkeypatch):
    """Threshold 3000s: the 3600s base cap alone would kill a tick that is still advancing."""
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_STUCK_SECONDS", 3000)
    assert g.tick_max_seconds() == 6000
    _old_receipt(6001)
    _active_tick(monkeypatch)
    _scoring_progress(0)
    # 20 checks = 4560s of watching: past the 3600s base cap, inside 2x the deadline.
    code, revives = _run_guard(monkeypatch, ticks=20, on_tick=lambda n: _scoring_progress(n))
    assert (code, revives) == (None, 0)


def test_a_tick_that_advances_forever_still_hits_the_absolute_cap(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    _old_receipt(6001)
    _active_tick(monkeypatch)
    _scoring_progress(0)
    code, _ = _run_guard(monkeypatch, ticks=30, on_tick=lambda n: _scoring_progress(n))
    assert code == 1


def test_tick_in_progress_revive_on_a_hung_tick_is_not_a_success(tmp_path, monkeypatch):
    """The revive cannot stop a hung tick: it is not marked done, the strikes stand and it retries."""
    _wire(tmp_path, monkeypatch)
    _old_receipt(6001)
    _active_tick(monkeypatch)
    _scoring_progress(5)
    code, revives = _run_guard(
        monkeypatch, ticks=20, revive=lambda n: {"revived": False, "reason": "tick_in_progress"}
    )
    assert code == 1
    assert revives == g.CONSECUTIVE_CHECKS


def test_real_revive_reports_tick_in_progress_for_an_active_tick(tmp_path, monkeypatch):
    """Replit's repro, end to end: the real revive says tick_in_progress; an advancing tick survives."""
    _wire(tmp_path, monkeypatch)
    _old_receipt(6001)
    _active_tick(monkeypatch)
    _scoring_progress(0)
    assert snaps.revive_score_snapshot_scheduler()["reason"] == "tick_in_progress"
    code, _ = _run_guard(
        monkeypatch, ticks=12, real_revive=True, on_tick=lambda n: _scoring_progress(n)
    )
    assert code is None


def test_real_revive_on_a_hung_tick_still_ends_in_a_restart(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    _old_receipt(6001)
    _active_tick(monkeypatch)
    _scoring_progress(5)
    code, _ = _run_guard(monkeypatch, ticks=20, real_revive=True)
    assert code == 1


def test_tick_in_progress_revive_on_a_premature_strike_is_withdrawn(tmp_path, monkeypatch):
    """A tick that started after the age check: the strike is withdrawn, not counted blindly."""
    _wire(tmp_path, monkeypatch)
    _old_receipt(6001)
    answers = iter([{"revived": False, "reason": "tick_in_progress"}])
    code, revives = _run_guard(
        monkeypatch,
        ticks=g.CONSECUTIVE_CHECKS,
        revive=lambda n: next(answers, {"revived": False, "reason": "no_change"}),
    )
    assert (code, revives) == (None, 2)


def test_withdrawn_strike_cannot_hold_off_the_restart_forever(tmp_path, monkeypatch):
    """If revive keeps saying tick_in_progress while the probe sees no tick, strikes still count."""
    _wire(tmp_path, monkeypatch)
    _old_receipt(6001)
    code, _ = _run_guard(
        monkeypatch,
        ticks=12,
        revive=lambda n: {"revived": False, "reason": "tick_in_progress"},
    )
    assert code == 1


def test_fresh_receipt_beats_old_seed_age(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    snaps.record_cycle_receipt({"complete": False}, outcome="incomplete")
    code, revives = _run_guard(monkeypatch)
    assert (code, revives) == (None, 0)


@pytest.mark.parametrize(
    "env",
    [
        {"STAGE2_HOP": "1"},
        {"SCORE_SNAPSHOT_SCHEDULER_ENABLED": "off"},
        {"WORKER_HEAVY": "off"},
    ],
    ids=["hop", "scheduler_off", "worker_heavy_off_not_owner"],
)
def test_non_producer_processes_never_strike_on_seed_age(tmp_path, monkeypatch, env):
    _wire(tmp_path, monkeypatch)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    code, revives = _run_guard(monkeypatch)
    assert revives == 0
    assert code in (None, "returned_idle")


@pytest.mark.parametrize(
    "env",
    [{"STAGE2_HOP": "1"}, {"SCORE_SNAPSHOT_SCHEDULER_ENABLED": "off"}, {"WORKER_HEAVY": "off"}],
    ids=["hop", "scheduler_off", "worker_heavy_off_not_owner"],
)
def test_non_producer_processes_never_strike_on_an_old_volume_file(tmp_path, monkeypatch, env):
    vol = _wire(tmp_path, monkeypatch)
    _write_volume(vol, age_seconds=100_000)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    code, revives = _run_guard(monkeypatch)
    assert revives == 0
    assert code in (None, "returned_idle")
