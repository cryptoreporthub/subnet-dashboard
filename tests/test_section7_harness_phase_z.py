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
    """Control for the test above: the pre-fix stop (SIGTERM to web only) does let the worker come back.

    The restart itself is asserted: after the worker is killed, the pid file must name a NEW pid, that
    pid must be alive and carry the run token, and it is not the worker that was killed.
    """
    import os
    import signal
    import time

    harness = _load_harness()
    proc = _start_real_entrypoint(harness, monkeypatch, tmp_path)
    try:
        old_worker = harness._worker_pid_from_pidfile()
        assert old_worker is not None and old_worker in harness._run_pids(harness.RUN_TOKEN)
        os.kill(proc.pid, signal.SIGTERM)  # web only, as before the fix
        proc.wait(timeout=10)
        assert harness._kill_worker_sigkill() is True
        deadline = time.monotonic() + 10
        new_worker = old_worker
        while time.monotonic() < deadline and new_worker == old_worker:
            time.sleep(0.2)
            new_worker = harness._worker_pid_from_pidfile()
        assert new_worker is not None and new_worker != old_worker, "the supervisor never restarted the worker"
        assert new_worker in harness._run_pids(harness.RUN_TOKEN)
        assert old_worker not in harness._run_pids(harness.RUN_TOKEN)
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
    sweeps = []

    def sweep(token, timeout=15.0):
        sweeps.append(token)
        return [4242] if len(sweeps) >= 2 else []  # clean before C, a survivor before Z

    monkeypatch.setattr(harness, "_kill_run_processes", sweep)
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


# --- full main() path with real processes (#1484 Replit P2: cleanup and the C restart) ---


def _worker_script(tmp_path):
    script = tmp_path / "worker.sh"
    script.write_text("exec sleep 300\n")
    return script


def _environ_of(pid):
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except OSError:
        return {}
    return dict(item.decode(errors="replace").split("=", 1) for item in raw if b"=" in item)


def _setup_real_main(monkeypatch, tmp_path, harness):
    import os
    import time

    monkeypatch.setattr(harness, "REPO", _fake_fly_repo(tmp_path))
    monkeypatch.setenv("PATH", f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("INLINE_WORKER_LAUNCH", f"sh {_worker_script(tmp_path)}")
    monkeypatch.setenv("INLINE_WORKER_SUPERVISOR_SLEEP_SECONDS", "1")
    monkeypatch.delenv("FINNEY_RPC_URL", raising=False)
    monkeypatch.delenv("BLOCKMACHINE_RPC_URL", raising=False)

    def workers():
        return [pid for pid in harness._run_pids(harness.RUN_TOKEN) if _environ_of(pid).get("RUN_MODE") == "worker"]

    def wait_for_worker():
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not workers():
            time.sleep(0.1)
        assert workers(), "worker never started"

    return workers, wait_for_worker


def _run_main(monkeypatch, tmp_path, *, fail_wait_on=None, fail_phase=None):
    harness = _load_harness()
    workers, wait_for_worker = _setup_real_main(monkeypatch, tmp_path, harness)
    seen = {}
    waits = []

    def wait_http(base, timeout=0):
        waits.append(1)
        wait_for_worker()
        return fail_wait_on != len(waits)

    def phase(label, base, seconds, snapshots_path, interval=3.0):
        wait_for_worker()
        seen[label] = [_environ_of(pid).get("FINNEY_RPC_URL") for pid in workers()]
        seen[label + "_pids"] = workers()
        if label == fail_phase:
            raise RuntimeError("boom")
        return harness.PhaseResult(label, 1, 0, 0, "fresh", 0), ["fresh"]

    monkeypatch.setattr(harness, "_wait_http", wait_http)
    monkeypatch.setattr(harness, "_phase", phase)
    try:
        code = harness.main()
    except RuntimeError:
        code = "raised"
    return harness, code, seen


def test_main_leaves_no_process_alive_on_success_and_c_workers_see_the_outage(monkeypatch, tmp_path):
    harness, code, seen = _run_main(monkeypatch, tmp_path)

    assert code in (0, 1)  # the pass/fail verdict is not what is under test
    assert harness._run_pids(harness.RUN_TOKEN) == []  # nothing outlives the run
    assert seen["R"] == [None]  # the earlier phases run without an outage
    assert seen["C"] == ["http://127.0.0.1:9"]  # C's worker carries the outage configuration
    assert not set(seen["R_pids"]) & set(seen["C_pids"])  # a new worker, not R's reused through the pidfile
    assert not set(seen["C_pids"]) & set(seen["Z_pids"])


def test_main_cleans_up_when_the_c_restart_never_becomes_ready(monkeypatch, tmp_path):
    harness, code, seen = _run_main(monkeypatch, tmp_path, fail_wait_on=3)  # F, R, then C

    assert code == 2
    assert "C" not in seen
    assert harness._run_pids(harness.RUN_TOKEN) == []


def test_main_cleans_up_when_the_first_start_never_becomes_ready(monkeypatch, tmp_path):
    harness, code, seen = _run_main(monkeypatch, tmp_path, fail_wait_on=1)

    assert code == 2
    assert harness._run_pids(harness.RUN_TOKEN) == []


def test_main_cleans_up_when_a_phase_raises(monkeypatch, tmp_path):
    harness, code, seen = _run_main(monkeypatch, tmp_path, fail_phase="C")

    assert code == "raised"
    assert harness._run_pids(harness.RUN_TOKEN) == []


# --- stop grace and unreadable processes (Claude item 3) ---


def test_stop_entrypoint_gives_the_supervisor_a_grace_period_before_kill(tmp_path):
    import subprocess
    import time

    harness = _load_harness()
    marker = tmp_path / "supervisor-exited-cleanly"
    script = tmp_path / "entry.sh"
    script.write_text(
        "( trap 'sleep 1; touch %s; exit 0' TERM; while :; do sleep 0.1; done ) &\n"
        "exec sh -c 'trap \"exit 0\" TERM; while :; do sleep 0.1; done'\n" % marker
    )
    proc = subprocess.Popen(["sh", str(script)], start_new_session=True)
    time.sleep(0.5)
    harness._stop_entrypoint(proc)

    assert marker.exists(), "the supervisor was SIGKILLed before it could finish its TERM handler"
    assert not harness._group_alive(proc.pid)


def test_stop_entrypoint_still_kills_a_group_member_that_ignores_term(tmp_path):
    import subprocess
    import time

    harness = _load_harness()
    script = tmp_path / "entry.sh"
    script.write_text(
        "( trap '' TERM; while :; do sleep 0.1; done ) &\n"
        "exec sh -c 'trap \"exit 0\" TERM; while :; do sleep 0.1; done'\n"
    )
    proc = subprocess.Popen(["sh", str(script)], start_new_session=True)
    time.sleep(0.5)
    harness._stop_entrypoint(proc)
    time.sleep(0.2)

    assert not harness._group_alive(proc.pid)


def _spawn_unreadable(harness, tmp_path):
    import os
    import subprocess
    import time

    code = "import ctypes,time; ctypes.CDLL(None).prctl(4,0,0,0,0); time.sleep(300)"  # PR_SET_DUMPABLE=0
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        env={**os.environ, harness.RUN_TOKEN_VAR: harness.RUN_TOKEN},
        start_new_session=True,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            Path(f"/proc/{proc.pid}/environ").read_bytes()
        except PermissionError:
            return proc
        except OSError:
            pass
        time.sleep(0.05)
    proc.kill()
    import pytest

    pytest.skip("cannot make a same-user process with an unreadable environment here")


def test_unreadable_process_in_a_run_session_counts_as_a_run_process(tmp_path):
    harness = _load_harness()
    proc = _spawn_unreadable(harness, tmp_path)
    try:
        assert proc.pid not in harness._run_pids(harness.RUN_TOKEN)  # unattributable until its session is ours
        harness._RUN_SESSIONS.add(proc.pid)
        assert proc.pid in harness._run_pids(harness.RUN_TOKEN)
        assert harness._kill_run_processes(harness.RUN_TOKEN, timeout=10) == []
        proc.wait(timeout=5)
    finally:
        proc.kill()
        proc.wait()


# --- the worker pid file is this run's own; a foreign pid in a shared one is never signalled (#1484 Replit P2) ---


def _spawn_foreign_worker():
    """A live process in its own session with no run token, like another app's or entrypoint's worker."""
    import os
    import subprocess

    env = {k: v for k, v in os.environ.items() if k != "S7_HARNESS_RUN_TOKEN"}
    return subprocess.Popen(["sleep", "300"], env=env, start_new_session=True)


def test_kill_worker_refuses_a_pid_that_does_not_carry_the_run_token(monkeypatch, tmp_path):
    harness = _load_harness()
    foreign = _spawn_foreign_worker()
    pidfile = tmp_path / "shared.pid"
    pidfile.write_text(str(foreign.pid))
    monkeypatch.setattr(harness, "PIDFILE", str(pidfile))
    try:
        assert harness._kill_worker_sigkill() is False
        assert foreign.poll() is None, "a foreign process listed in the pid file was killed"
        assert foreign.pid not in harness._run_sessions()
    finally:
        foreign.kill()
        foreign.wait()


def test_kill_worker_still_kills_a_worker_that_carries_the_run_token(monkeypatch, tmp_path):
    import os
    import subprocess

    harness = _load_harness()
    mine = subprocess.Popen(
        ["sleep", "300"], env={**os.environ, harness.RUN_TOKEN_VAR: harness.RUN_TOKEN}, start_new_session=True
    )
    pidfile = tmp_path / "run.pid"
    pidfile.write_text(str(mine.pid))
    monkeypatch.setattr(harness, "PIDFILE", str(pidfile))
    try:
        assert harness._kill_worker_sigkill() is True
        mine.wait(timeout=5)
    finally:
        mine.kill()
        mine.wait()


def test_fly_env_uses_a_pid_file_inside_the_run_directory_not_the_shared_one(monkeypatch, tmp_path):
    monkeypatch.setenv("INLINE_WORKER_PIDFILE", "/tmp/inline_worker.pid")
    harness = _load_harness()  # its module default is the inherited/shared path
    assert harness.PIDFILE == "/tmp/inline_worker.pid"

    env = harness._fly_env(tmp_path, "0", seed_path=str(tmp_path / "seed.json"))

    assert env["INLINE_WORKER_PIDFILE"] == str(tmp_path / "inline_worker.pid")


def test_main_neither_reuses_nor_kills_a_foreign_worker_from_the_shared_pid_file(monkeypatch, tmp_path):
    foreign = _spawn_foreign_worker()
    shared = tmp_path / "shared-inline-worker.pid"
    shared.write_text(str(foreign.pid))
    monkeypatch.setenv("INLINE_WORKER_PIDFILE", str(shared))  # what the module defaults to, as in production
    try:
        harness, code, seen = _run_main(monkeypatch, tmp_path)

        assert code in (0, 1)
        assert foreign.poll() is None, "the harness killed a worker it did not start"
        assert shared.read_text() == str(foreign.pid)  # the shared pid file was never touched
        started = set(seen["R_pids"]) | set(seen["C_pids"]) | set(seen["Z_pids"])
        assert foreign.pid not in started  # and never adopted as the run's worker
        assert harness._run_pids(harness.RUN_TOKEN) == []  # only what this run started is gone
    finally:
        foreign.kill()
        foreign.wait()
