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


def _fake_fly_repo(tmp_path):
    """A repo dir with the real fly entrypoint but stubbed boot steps, web and worker launch."""
    scripts = tmp_path / "repo" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "fly_web_entrypoint.sh").write_text((REPO / "scripts" / "fly_web_entrypoint.sh").read_text())
    (scripts / "tmp_boot_reap_once.py").write_text("")
    (scripts / "run_web_with_guard.py").write_text("import time\nwhile True:\n    time.sleep(1)\n")
    return tmp_path / "repo"


def _stop_like_phase_z(harness, proc):
    harness._stop_entrypoint(proc)
    harness._kill_worker_sigkill()
    return harness._kill_run_processes(harness.RUN_TOKEN, timeout=10)


def _start_real_entrypoint(harness, monkeypatch, tmp_path):
    import os
    import time

    monkeypatch.setattr(harness, "REPO", _fake_fly_repo(tmp_path))
    monkeypatch.setattr(harness, "PIDFILE", str(tmp_path / "worker.pid"))
    env = harness._fly_env(tmp_path, "0", seed_path=str(tmp_path / "missing_seed.json"))
    env.update(
        {
            "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
            "INLINE_WORKER_LAUNCH": "sleep 300",  # stands in for `python -m internal.worker`
            "INLINE_WORKER_SUPERVISOR_SLEEP_SECONDS": "1",
            "INLINE_WORKER_PIDFILE": str(tmp_path / "worker.pid"),
        }
    )
    proc = harness._start_entrypoint(env)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and len(harness._run_pids(harness.RUN_TOKEN)) < 3:
        time.sleep(0.1)  # web, the supervisor subshell and the worker
    assert len(harness._run_pids(harness.RUN_TOKEN)) >= 3, "entrypoint never reached web + supervisor + worker"
    return proc


def test_phase_z_stop_really_kills_web_supervisor_and_worker(monkeypatch, tmp_path):
    """Behavioural: nothing from the entrypoint is alive afterwards, and nothing comes back (#1484 Ditto r6).

    The supervisor wakes every second here and (no heartbeat module in the stub repo) restarts the
    worker each time. If it survived the stop, a worker would reappear within a second.
    """
    import time

    harness = _load_harness()
    proc = _start_real_entrypoint(harness, monkeypatch, tmp_path)
    try:
        assert _stop_like_phase_z(harness, proc) == []
        time.sleep(3)  # three supervisor wake-ups
        assert harness._run_pids(harness.RUN_TOKEN) == []
    finally:
        harness._kill_run_processes(harness.RUN_TOKEN, timeout=5)


def test_stopping_only_the_web_pid_leaves_a_supervisor_that_restarts_the_worker(monkeypatch, tmp_path):
    """Control for the test above: the pre-fix stop (SIGTERM to web only) does let the worker come back."""
    import os
    import signal
    import time

    harness = _load_harness()
    proc = _start_real_entrypoint(harness, monkeypatch, tmp_path)
    try:
        os.kill(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
        harness._kill_worker_sigkill()
        time.sleep(3)
        assert harness._run_pids(harness.RUN_TOKEN), "supervisor should have survived and restarted the worker"
    finally:
        harness._kill_run_processes(harness.RUN_TOKEN, timeout=5)


def test_phase_z_does_not_clear_the_volume_if_a_process_of_the_run_survives(monkeypatch):
    events = []
    harness = _load_harness()

    def start(env):
        events.append("start")
        return _Proc()

    monkeypatch.setattr(harness, "_start_entrypoint", start)
    monkeypatch.setattr(harness, "_wait_http", lambda *a, **k: True)
    monkeypatch.setattr(harness, "_phase", lambda label, *a, **k: (harness.PhaseResult(label, 1, 0, 0, "fresh", 0), ["fresh"]))
    monkeypatch.setattr(harness, "_stop_entrypoint", lambda proc: None)
    monkeypatch.setattr(harness, "_kill_worker_sigkill", lambda: True)
    monkeypatch.setattr(harness, "_kill_run_processes", lambda token, timeout=15.0: [4242])
    monkeypatch.setattr(harness, "_clear_volume", lambda data_dir: events.append("clear"))
    monkeypatch.setattr(harness.time, "sleep", lambda s: None)

    assert harness.main() == 2
    assert "clear" not in events
    assert events.count("start") == 3  # F, W-restart, C-restart; Z never launched


def test_stop_entrypoint_alone_takes_the_supervisor_down_with_web(monkeypatch, tmp_path):
    """Without the final sweep: stop + worker kill must already leave nothing to revive the worker."""
    import time

    harness = _load_harness()
    proc = _start_real_entrypoint(harness, monkeypatch, tmp_path)
    try:
        harness._stop_entrypoint(proc)
        harness._kill_worker_sigkill()
        time.sleep(3)
        assert harness._run_pids(harness.RUN_TOKEN) == []
    finally:
        harness._kill_run_processes(harness.RUN_TOKEN, timeout=5)
