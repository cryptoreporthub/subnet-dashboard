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


def _run_guard(monkeypatch, *, ticks=4, revive_writes_receipt=False):
    """Run the real guard loop for ``ticks`` ticks. Returns (exit_code, revives)."""
    revives = []

    def _revive():
        revives.append(1)
        if revive_writes_receipt:
            snaps.record_cycle_receipt({"complete": False}, outcome="incomplete")

    state = {"n": 0}

    def _sleep(_s):
        state["n"] += 1
        if state["n"] > ticks:
            raise _Stop()

    def _exit(code):
        raise _Exit(code)

    monkeypatch.setattr(g, "ENABLED", True)
    monkeypatch.setattr(g, "KILL_ENABLED", True)
    monkeypatch.setattr(g, "BOOT_GRACE_SECONDS", 0)
    monkeypatch.setattr(g, "CONSECUTIVE_CHECKS", 3)
    monkeypatch.setattr(g, "MAX_SNAPSHOT_AGE_SECONDS", 5400)
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
