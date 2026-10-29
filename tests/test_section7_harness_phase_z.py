"""Phase Z of the §7 harness is the no-volume, no-seed start (#1484 round 3).

It reused the data dir of phases F/W/R/C, so the volume snapshot built in phase F was still there and
the cold start it claims to exercise never happened.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_harness():
    spec = importlib.util.spec_from_file_location("section7_harness_under_test", REPO / "scripts" / "score_snapshot_section7_harness.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Proc:
    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def _run_with_fakes(monkeypatch, *, write_volume_on_launch, events=None):
    harness = _load_harness()
    launches = []
    events = events if events is not None else []

    def start(env):
        data_dir = Path(env["DATA_DIR"])
        volume = data_dir / "score_snapshots.json"
        leftovers = sorted(
            p.name for p in (volume, volume.with_name(volume.name + ".lock"), data_dir / "score_snapshot_cycle.json") if p.exists()
        )
        lock = volume.with_name(volume.name + ".lock")
        launches.append(
            {
                "seed": env["SCORE_SNAPSHOT_SEED_PATH"],
                "volume_present": volume.exists(),
                "leftovers": leftovers,
                "lock_inode": lock.stat().st_ino if lock.exists() else None,
            }
        )
        events.append("start")
        if write_volume_on_launch:  # what phase F's build leaves behind
            volume.write_text('{"day": [1]}')
            (data_dir / "score_snapshot_cycle.json").write_text("{}")
            lock = volume.with_name(volume.name + ".lock")
            if not lock.exists():  # the producer opens it append-mode: created once, never replaced
                lock.write_text("")
        return _Proc()

    def phase(label, base, seconds, snapshots_path, interval=3.0):
        return harness.PhaseResult(label, 1, 0, 0, "fresh", 0), ["fresh"]

    monkeypatch.setattr(harness, "_start_entrypoint", start)
    monkeypatch.setattr(harness, "_wait_http", lambda *a, **k: True)
    monkeypatch.setattr(harness, "_phase", phase)
    monkeypatch.setattr(harness, "_stop_entrypoint", lambda proc: events.append("stop"))
    monkeypatch.setattr(harness, "_kill_worker_sigkill", lambda: events.append("kill_worker") or True)
    monkeypatch.setattr(harness.time, "sleep", lambda s: None)
    real_clear = harness._clear_volume

    def clear(data_dir):
        events.append("clear")
        real_clear(data_dir)

    monkeypatch.setattr(harness, "_clear_volume", clear)
    harness.main()
    return launches


def test_phase_z_starts_with_no_volume_file_even_though_earlier_phases_built_one(monkeypatch):
    launches = _run_with_fakes(monkeypatch, write_volume_on_launch=True)

    z = launches[-1]
    assert z["seed"].endswith("missing_seed.json")
    assert z["volume_present"] is False


def test_the_earlier_phases_still_see_the_volume_they_built(monkeypatch):
    launches = _run_with_fakes(monkeypatch, write_volume_on_launch=True)

    # F starts cold; W-restart, C-restart reuse the same data dir on purpose (that is what they test).
    assert [launch["volume_present"] for launch in launches[:-1]] == [False, True, True]


def test_phase_z_also_clears_the_producer_receipt_of_the_earlier_phases(monkeypatch):
    launches = _run_with_fakes(monkeypatch, write_volume_on_launch=True)

    assert launches[0]["leftovers"] == []
    # Only the snapshot and the receipt are cold-volume state; the lock file is synchronisation
    # metadata and is deliberately left alone (see the inode test below).
    assert launches[-1]["leftovers"] == ["score_snapshots.json.lock"]


def test_phase_z_keeps_the_snapshot_lock_inode_stable(monkeypatch):
    """Unlinking the lock would let a surviving writer keep the old inode while a new one locks a new inode (#1484 Ditto r5)."""
    launches = _run_with_fakes(monkeypatch, write_volume_on_launch=True)

    inodes = [launch["lock_inode"] for launch in launches[1:]]
    assert None not in inodes
    assert len(set(inodes)) == 1


def test_phase_z_stops_the_inline_worker_before_clearing_the_volume(monkeypatch):
    events = []
    _run_with_fakes(monkeypatch, write_volume_on_launch=True, events=events)

    clear = events.index("clear")
    last_stop_before_clear = max(i for i, event in enumerate(events[:clear]) if event == "stop")
    assert "kill_worker" in events[last_stop_before_clear:clear]
