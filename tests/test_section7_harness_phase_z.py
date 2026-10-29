"""Phase Z of the §7 harness is the no-volume, no-seed start (#1484 round 3).

It reused the data dir of phases F/W/R/C, so the volume snapshot built in phase F was still there and
the cold start it claims to exercise never happened.
"""

from __future__ import annotations

import importlib.util
import sys

import pytest
from pathlib import Path


def _host_pidfd_unavailable_reason():
    """None when this host can really open and signal a pidfd; otherwise why not.

    The harness refuses to run without working pidfds (``main()`` exits 2), so tests that drive real
    cleanup or ``main()`` can only run where the real calls work; elsewhere they skip, not fail.
    """
    import os
    import signal

    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        return "pidfd is not available on this host"
    try:
        fd = os.pidfd_open(os.getpid())
    except OSError as exc:
        return f"pidfd_open is blocked on this host: {exc}"
    try:
        signal.pidfd_send_signal(fd, 0)
    except OSError as exc:
        return f"pidfd_send_signal is blocked on this host: {exc}"
    finally:
        os.close(fd)
    return None


_PIDFD_UNAVAILABLE = _host_pidfd_unavailable_reason()
requires_real_pidfd = pytest.mark.skipif(_PIDFD_UNAVAILABLE is not None, reason=_PIDFD_UNAVAILABLE or "")

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


@requires_real_pidfd
def test_phase_z_starts_with_no_volume_file_even_though_earlier_phases_built_one(monkeypatch):
    launches = _run_with_fakes(monkeypatch, write_volume_on_launch=True)

    z = launches[-1]
    assert z["seed"].endswith("missing_seed.json")
    assert z["volume_present"] is False


@requires_real_pidfd
def test_the_earlier_phases_still_see_the_volume_they_built(monkeypatch):
    launches = _run_with_fakes(monkeypatch, write_volume_on_launch=True)

    # F starts cold; W-restart, C-restart reuse the same data dir on purpose (that is what they test).
    assert [launch["volume_present"] for launch in launches[:-1]] == [False, True, True]


@requires_real_pidfd
def test_phase_z_also_clears_the_producer_receipt_of_the_earlier_phases(monkeypatch):
    launches = _run_with_fakes(monkeypatch, write_volume_on_launch=True)

    assert launches[0]["leftovers"] == []
    # Only the snapshot and the receipt are cold-volume state; the lock file is synchronisation
    # metadata and is deliberately left alone (see the inode test below).
    assert launches[-1]["leftovers"] == ["score_snapshots.json.lock"]


@requires_real_pidfd
def test_phase_z_keeps_the_snapshot_lock_inode_stable(monkeypatch):
    """Unlinking the lock would let a surviving writer keep the old inode while a new one locks a new inode (#1484 Ditto r5)."""
    launches = _run_with_fakes(monkeypatch, write_volume_on_launch=True)

    inodes = [launch["lock_inode"] for launch in launches[1:]]
    assert None not in inodes
    assert len(set(inodes)) == 1


@requires_real_pidfd
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


@requires_real_pidfd
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


@requires_real_pidfd
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


@requires_real_pidfd
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


@requires_real_pidfd
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


def _run_main(monkeypatch, tmp_path, *, fail_wait_on=None, fail_phase=None, on_phase=None):
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
        if on_phase is not None:
            on_phase(harness, label)
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


@requires_real_pidfd
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


@requires_real_pidfd
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
    proc = subprocess.Popen(["sh", str(script)], env=_token_env(harness), start_new_session=True)
    time.sleep(0.5)
    harness._stop_entrypoint(proc)

    assert marker.exists(), "the supervisor was SIGKILLed before it could finish its TERM handler"
    assert not harness._group_alive(proc.pid)


@requires_real_pidfd
def test_stop_entrypoint_still_kills_a_group_member_that_ignores_term(tmp_path):
    import subprocess
    import time

    harness = _load_harness()
    script = tmp_path / "entry.sh"
    script.write_text(
        "( trap '' TERM; while :; do sleep 0.1; done ) &\n"
        "exec sh -c 'trap \"exit 0\" TERM; while :; do sleep 0.1; done'\n"
    )
    proc = subprocess.Popen(["sh", str(script)], env=_token_env(harness), start_new_session=True)
    time.sleep(0.5)
    harness._stop_entrypoint(proc)
    time.sleep(0.2)

    assert not harness._group_alive(proc.pid)


def _token_env(harness, with_token=True):
    import os

    env = {k: v for k, v in os.environ.items() if k != harness.RUN_TOKEN_VAR}
    if with_token:
        env[harness.RUN_TOKEN_VAR] = harness.RUN_TOKEN
    return env


def _orphan_group(harness, tmp_path, *, with_token):
    """A group whose leader has already exited (and is reaped), leaving one member that ignores TERM."""
    import subprocess
    import time

    script = tmp_path / ("entry-token.sh" if with_token else "entry-foreign.sh")
    script.write_text("( trap '' TERM; while :; do sleep 0.1; done ) &\nexit 0\n")
    proc = subprocess.Popen(["sh", str(script)], env=_token_env(harness, with_token), start_new_session=True)
    proc.wait(timeout=5)  # the leader is gone and reaped; its group lives on through the member
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not harness._group_alive(proc.pid):
        time.sleep(0.05)
    assert harness._group_alive(proc.pid)
    return proc


@requires_real_pidfd
def test_stop_entrypoint_kills_a_leaderless_group_member_that_carries_the_run_token(tmp_path):
    import time

    harness = _load_harness()
    proc = _orphan_group(harness, tmp_path, with_token=True)
    try:
        harness._stop_entrypoint(proc)
        deadline = time.monotonic() + 3  # the member's last ``sleep 0.1`` child may still be finishing
        while time.monotonic() < deadline and harness._group_alive(proc.pid):
            time.sleep(0.05)
        assert not harness._group_alive(proc.pid)
    finally:
        harness._signal_group_members(proc.pid, 9)


def test_stop_entrypoint_never_kills_a_leaderless_group_member_it_cannot_prove_is_the_runs(tmp_path):
    """Once the leader is reaped the group id may name someone else's group: no token, no signal."""
    import os
    import signal

    harness = _load_harness()
    proc = _orphan_group(harness, tmp_path, with_token=False)
    members = harness._group_members(proc.pid)
    try:
        harness._stop_entrypoint(proc)
        assert harness._group_alive(proc.pid), "a group member without the run token was signalled"
    finally:
        for pid in members:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


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


def test_unreadable_process_in_a_run_session_is_reported_but_never_signalled(tmp_path):
    """A process whose environment cannot be read is not provably the run's: it is never SIGKILLed.

    It sits in a session this run created, so a cleanup that leaves it behind reports it as a survivor
    (the run then exits 2) instead of killing a process that, after pid recycling, may not be ours.
    """
    harness = _load_harness()
    proc = _spawn_unreadable(harness, tmp_path)
    try:
        assert proc.pid not in harness._run_pids(harness.RUN_TOKEN)  # unattributable until its session is ours
        assert harness._unattributable_run_pids(harness.RUN_TOKEN) == []
        harness._RUN_SESSIONS.add(proc.pid)
        try:
            assert proc.pid not in harness._run_pids(harness.RUN_TOKEN)  # still not proof: never a kill target
            assert harness._unattributable_run_pids(harness.RUN_TOKEN) == [proc.pid]
            assert harness._kill_run_processes(harness.RUN_TOKEN, timeout=2) == [proc.pid]  # reported
            harness._stop_run()
            assert _still_alive(proc), "an unreadable-environment process was SIGKILLed"
        finally:
            harness._RUN_SESSIONS.discard(proc.pid)
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
        assert _still_alive(foreign), "a foreign process listed in the pid file was killed"
        assert foreign.pid not in harness._run_sessions()
    finally:
        foreign.kill()
        foreign.wait()


@requires_real_pidfd
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


@requires_real_pidfd
def test_main_neither_reuses_nor_kills_a_foreign_worker_from_the_shared_pid_file(monkeypatch, tmp_path):
    foreign = _spawn_foreign_worker()
    shared = tmp_path / "shared-inline-worker.pid"
    shared.write_text(str(foreign.pid))
    monkeypatch.setenv("INLINE_WORKER_PIDFILE", str(shared))  # what the module defaults to, as in production
    try:
        harness, code, seen = _run_main(monkeypatch, tmp_path)

        assert code in (0, 1)
        assert _still_alive(foreign), "the harness killed a worker it did not start"
        assert shared.read_text() == str(foreign.pid)  # the shared pid file was never touched
        started = set(seen["R_pids"]) | set(seen["C_pids"]) | set(seen["Z_pids"])
        assert foreign.pid not in started  # and never adopted as the run's worker
        assert harness._run_pids(harness.RUN_TOKEN) == []  # only what this run started is gone
    finally:
        foreign.kill()
        foreign.wait()


@requires_real_pidfd
def test_main_never_kills_a_foreign_pid_that_lands_in_the_runs_own_pid_file(monkeypatch, tmp_path):
    """The token check itself, through the real ``main()`` path (#1484 Claude r8).

    The run's pid file is private, so a foreign pid can only get into it by accident (a stale file, pid
    reuse). Here it is planted during the last phase, so the final cleanup's ``_kill_worker_sigkill``
    reads it. Without the token check that SIGKILLs the foreign process.
    """
    foreign = _spawn_foreign_worker()
    planted = []

    def plant(harness, label):
        if label == "Z":
            Path(harness.PIDFILE).write_text(str(foreign.pid))
            planted.append(Path(harness.PIDFILE).read_text())

    try:
        harness, code, seen = _run_main(monkeypatch, tmp_path, on_phase=plant)

        assert planted == [str(foreign.pid)]  # the pid file really named the foreign process at cleanup time
        assert code in (0, 1)
        assert _still_alive(foreign), "the harness SIGKILLed a pid from its pid file that lacks the run token"
        assert harness._run_pids(harness.RUN_TOKEN) == []  # the run's own processes are all gone
    finally:
        foreign.kill()
        foreign.wait()


# --- zombies, and the exit code when cleanup leaves a process behind (#1484 Claude) ---


def test_group_alive_ignores_an_unreaped_zombie():
    import os
    import subprocess
    import time

    harness = _load_harness()
    code = (
        "import os, sys, time\n"
        "r, w = os.pipe()\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    os.setpgid(0, 0)\n"  # a group of one, which exits at once
        "    os.write(w, str(os.getpid()).encode()); os._exit(0)\n"
        "print(os.read(r, 32).decode(), flush=True)\n"
        "time.sleep(300)\n"  # the parent never reaps it
    )
    parent = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        zombie = int(parent.stdout.readline())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if Path(f"/proc/{zombie}/stat").read_text().rsplit(")", 1)[-1].split()[0] == "Z":
                break
            time.sleep(0.05)
        assert Path(f"/proc/{zombie}/stat").read_text().rsplit(")", 1)[-1].split()[0] == "Z"
        os.killpg(zombie, 0)  # the plain signal check still sees the zombie: why it cannot be used
        assert harness._group_alive(zombie) is False
    finally:
        parent.kill()
        parent.wait()


@requires_real_pidfd
def test_main_exits_2_when_the_final_cleanup_leaves_a_process_behind(monkeypatch):
    harness = _load_harness()
    monkeypatch.setattr(harness, "_start_entrypoint", lambda env: _Proc())
    monkeypatch.setattr(harness, "_wait_http", lambda *a, **k: True)
    monkeypatch.setattr(
        harness, "_phase", lambda label, *a, **k: (harness.PhaseResult(label, 1, 0, 0, "fresh", 0), ["fresh"])
    )
    monkeypatch.setattr(harness, "_stop_entrypoint", lambda proc: None)
    monkeypatch.setattr(harness, "_kill_worker_sigkill", lambda: True)
    sweeps = []

    def sweep(token, timeout=15.0):
        sweeps.append(1)
        return [4242] if len(sweeps) >= 3 else []  # clean before C and Z, a survivor in the final cleanup

    monkeypatch.setattr(harness, "_kill_run_processes", sweep)
    monkeypatch.setattr(harness, "_clear_volume", lambda data_dir: None)
    monkeypatch.setattr(harness.time, "sleep", lambda s: None)

    assert harness.main() == 2
    assert len(sweeps) == 3  # all phases ran; only the cleanup failed


@requires_real_pidfd
def test_main_exits_2_when_a_phase_raises_and_the_final_cleanup_leaves_a_process_behind(monkeypatch, capsys):
    """The exception path: a survivor still decides the exit code (#1484 Ditto r8 / Claude r8)."""
    harness = _load_harness()
    monkeypatch.setattr(harness, "_start_entrypoint", lambda env: _Proc())
    monkeypatch.setattr(harness, "_wait_http", lambda *a, **k: True)

    def phase(label, *a, **k):
        if label == "R":
            raise RuntimeError("boom")
        return harness.PhaseResult(label, 1, 0, 0, "fresh", 0), ["fresh"]

    monkeypatch.setattr(harness, "_phase", phase)
    monkeypatch.setattr(harness, "_stop_entrypoint", lambda proc: None)
    monkeypatch.setattr(harness, "_kill_worker_sigkill", lambda: True)
    monkeypatch.setattr(harness, "_kill_run_processes", lambda token, timeout=15.0: [4242])  # the cleanup leaves one
    monkeypatch.setattr(harness, "_clear_volume", lambda data_dir: None)
    monkeypatch.setattr(harness.time, "sleep", lambda s: None)

    assert harness.main() == 2
    err = capsys.readouterr().err
    assert "processes still alive after cleanup: [4242]" in err
    assert "RuntimeError: boom" in err  # the original failure is still shown


@requires_real_pidfd
def test_main_still_raises_the_phase_exception_when_the_cleanup_is_clean(monkeypatch):
    harness = _load_harness()
    monkeypatch.setattr(harness, "_start_entrypoint", lambda env: _Proc())
    monkeypatch.setattr(harness, "_wait_http", lambda *a, **k: True)

    def phase(label, *a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(harness, "_phase", phase)
    monkeypatch.setattr(harness, "_stop_entrypoint", lambda proc: None)
    monkeypatch.setattr(harness, "_kill_worker_sigkill", lambda: True)
    monkeypatch.setattr(harness, "_kill_run_processes", lambda token, timeout=15.0: [])
    monkeypatch.setattr(harness, "_clear_volume", lambda data_dir: None)
    monkeypatch.setattr(harness.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError, match="boom"):
        harness.main()


# --- ownership check and signal share one pidfd: a reused pid is never signalled (#1484 Replit r9 P2) ---


class _Reuse:
    """Models pid reuse: ``swap()`` ends the owned process, after which every raw-pid signal or pidfd
    open aimed at its pid reaches the foreign process instead, as the kernel would after recycling."""

    def __init__(self, monkeypatch, harness, owned, foreign):
        import os

        self.owned, self.foreign, self.swapped = owned, foreign, False
        real_kill, real_killpg, real_open = os.kill, os.killpg, os.pidfd_open

        def retarget(pid):
            return self.foreign.pid if self.swapped and pid == self.owned.pid else pid

        monkeypatch.setattr(harness.os, "kill", lambda pid, sig: real_kill(retarget(pid), sig))
        monkeypatch.setattr(harness.os, "killpg", lambda pid, sig: real_killpg(retarget(pid), sig))
        monkeypatch.setattr(harness.os, "pidfd_open", lambda pid, *a: real_open(retarget(pid), *a))

    def swap(self):
        if not self.swapped:
            self.owned.kill()
            self.owned.wait(timeout=5)
            self.swapped = True


def _owned_and_foreign(harness):
    import os
    import subprocess

    owned = subprocess.Popen(
        ["sleep", "300"], env={**os.environ, harness.RUN_TOKEN_VAR: harness.RUN_TOKEN}, start_new_session=True
    )
    foreign = _spawn_foreign_worker()
    return owned, foreign


def _still_alive(proc, grace=0.5):
    """True if ``proc`` is still running after ``grace`` s (a SIGKILL is delivered asynchronously, so
    an immediate ``poll()`` can miss a kill that is already on its way)."""
    import subprocess

    try:
        proc.wait(timeout=grace)
        return False
    except subprocess.TimeoutExpired:
        return True


def _cleanup_procs(*procs):
    for proc in procs:
        proc.kill()
        proc.wait()


def _swap_after_the_ownership_check(monkeypatch, harness, reuse):
    """The pid changes hands right after the token check, before the signal is sent."""
    real = harness._carries_run_token

    def check(pid, *args):
        verdict = real(pid, *args)
        if pid == reuse.owned.pid:
            reuse.swap()
        return verdict  # still True: the check itself passed before the swap

    monkeypatch.setattr(harness, "_carries_run_token", check)


@requires_real_pidfd
def test_worker_kill_never_signals_a_pid_reused_between_the_check_and_the_signal(monkeypatch, tmp_path):
    harness = _load_harness()
    owned, foreign = _owned_and_foreign(harness)
    pidfile = tmp_path / "run.pid"
    pidfile.write_text(str(owned.pid))
    monkeypatch.setattr(harness, "PIDFILE", str(pidfile))
    reuse = _Reuse(monkeypatch, harness, owned, foreign)
    _swap_after_the_ownership_check(monkeypatch, harness, reuse)
    try:
        harness._kill_worker_sigkill()
        assert reuse.swapped
        assert _still_alive(foreign), "a process that reused the worker's pid was SIGKILLed"
    finally:
        _cleanup_procs(owned, foreign)


@requires_real_pidfd
def test_group_signal_never_signals_a_pid_reused_between_the_check_and_the_signal(monkeypatch):
    import signal

    harness = _load_harness()
    owned, foreign = _owned_and_foreign(harness)
    reuse = _Reuse(monkeypatch, harness, owned, foreign)
    _swap_after_the_ownership_check(monkeypatch, harness, reuse)
    try:
        harness._signal_group_members(owned.pid, signal.SIGKILL)
        assert reuse.swapped
        assert _still_alive(foreign), "a process that reused a group member's pid was signalled"
    finally:
        _cleanup_procs(owned, foreign)


@requires_real_pidfd
def test_run_sweep_never_signals_a_pid_reused_between_the_scan_and_the_kill(monkeypatch):
    harness = _load_harness()
    owned, foreign = _owned_and_foreign(harness)
    reuse = _Reuse(monkeypatch, harness, owned, foreign)
    real_scan = harness._run_pids

    def scan(token):
        pids = real_scan(token)
        if owned.pid in pids:
            reuse.swap()  # the scan saw the run's process; by the time it is signalled the pid is someone else's
        return pids

    monkeypatch.setattr(harness, "_run_pids", scan)
    try:
        harness._kill_run_processes(harness.RUN_TOKEN, timeout=3)
        assert reuse.swapped
        assert _still_alive(foreign), "the sweep SIGKILLed a process that reused a run pid"
    finally:
        _cleanup_procs(owned, foreign)


@requires_real_pidfd
def test_signal_dispatch_after_a_verified_pidfd_cannot_reach_a_reused_pid(monkeypatch):
    """The pidfd, not the pid, names the target: the owned process ends right before the signal is sent."""
    import signal

    harness = _load_harness()
    owned, foreign = _owned_and_foreign(harness)
    reuse = _Reuse(monkeypatch, harness, owned, foreign)
    real_send = signal.pidfd_send_signal

    def send(fd, sig, *args):
        reuse.swap()
        return real_send(fd, sig, *args)

    monkeypatch.setattr(harness.signal, "pidfd_send_signal", send)
    try:
        assert harness._signal_run_process(owned.pid, signal.SIGKILL) is False  # the owned process was already gone
        assert reuse.swapped
        assert _still_alive(foreign)
    finally:
        _cleanup_procs(owned, foreign)


@requires_real_pidfd
def test_a_process_that_exits_while_its_environment_is_read_is_not_verified(monkeypatch):
    """The environ read is only trusted when the pidfd shows the process was alive throughout."""
    harness = _load_harness()
    owned, foreign = _owned_and_foreign(harness)
    reuse = _Reuse(monkeypatch, harness, owned, foreign)
    _swap_after_the_ownership_check(monkeypatch, harness, reuse)
    try:
        assert harness._open_run_pidfd(owned.pid) is None
    finally:
        _cleanup_procs(owned, foreign)


def _force_pidfds_onto_high_fds(monkeypatch, harness, minimum=1024):
    """Make every pidfd the harness opens land on an fd >= FD_SETSIZE (1024), where select.select raises."""
    import fcntl
    import os
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    need = minimum + 64
    if soft != resource.RLIM_INFINITY and soft < need:
        resource.setrlimit(resource.RLIMIT_NOFILE, (need if hard == resource.RLIM_INFINITY else min(need, hard), hard))
    opened = []
    real_open = harness.os.pidfd_open

    def high_open(pid, flags=0):
        low = real_open(pid, flags)
        try:
            high = fcntl.fcntl(low, fcntl.F_DUPFD, minimum)
        finally:
            os.close(low)
        opened.append(high)
        return high

    monkeypatch.setattr(harness.os, "pidfd_open", high_open)
    return opened, (soft, hard)


def _fd_is_open(fd):
    import os

    try:
        os.fstat(fd)
        return True
    except OSError:
        return False


@requires_real_pidfd
def test_a_pidfd_on_a_high_fd_is_verified_and_signalled(monkeypatch):
    """select.select raises ValueError for fd >= 1024; the liveness check must not depend on it."""
    import os
    import resource
    import signal

    harness = _load_harness()
    owned, foreign = _owned_and_foreign(harness)
    opened, limits = _force_pidfds_onto_high_fds(monkeypatch, harness)
    try:
        fd = harness._open_run_pidfd(owned.pid)
        assert fd is not None and fd >= 1024 and fd in opened
        os.close(fd)
        assert harness._signal_run_process(owned.pid, signal.SIGKILL) is True
        assert not _still_alive(owned)
        assert _still_alive(foreign)
    finally:
        _cleanup_procs(owned, foreign)
        for fd in opened:
            if _fd_is_open(fd):
                os.close(fd)
        resource.setrlimit(resource.RLIMIT_NOFILE, limits)


@requires_real_pidfd
def test_a_high_fd_pidfd_is_closed_and_not_returned_when_the_check_fails(monkeypatch):
    """Fail closed without leaking: an unexpected error in the liveness check closes the fd and returns None."""
    import os
    import resource

    harness = _load_harness()
    owned, foreign = _owned_and_foreign(harness)
    opened, limits = _force_pidfds_onto_high_fds(monkeypatch, harness)

    def broken(fd):
        raise ValueError("filedescriptor out of range in select()")

    monkeypatch.setattr(harness, "_pidfd_has_exited", broken)
    try:
        assert harness._open_run_pidfd(owned.pid) is None
        assert opened and not any(_fd_is_open(fd) for fd in opened)  # no leaked fd
        assert _still_alive(owned)  # nothing was signalled
    finally:
        _cleanup_procs(owned, foreign)
        for fd in opened:
            if _fd_is_open(fd):
                os.close(fd)
        resource.setrlimit(resource.RLIMIT_NOFILE, limits)


def test_cleanup_paths_never_signal_by_raw_pid():
    """No cleanup path calls os.kill / os.killpg; only the unreaped-leader group helper may use killpg."""
    import ast

    source = (REPO / "scripts" / "score_snapshot_section7_harness.py").read_text()
    tree = ast.parse(source)
    offenders = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
            f = call.func
            if isinstance(f, ast.Attribute) and f.attr in {"kill", "killpg"} and getattr(f.value, "id", "") == "os":
                if fn.name != "_killpg":
                    offenders.append((fn.name, f.attr))
    assert offenders == []


def test_without_pidfd_nothing_is_signalled_and_main_refuses_to_start(monkeypatch, tmp_path, capsys):
    import signal

    harness = _load_harness()
    owned, foreign = _owned_and_foreign(harness)
    pidfile = tmp_path / "run.pid"
    pidfile.write_text(str(owned.pid))
    monkeypatch.setattr(harness, "PIDFILE", str(pidfile))
    monkeypatch.setattr(harness, "_PIDFD_SUPPORTED", False)
    started = []
    monkeypatch.setattr(harness, "_start_entrypoint", lambda env: started.append(1))
    try:
        assert harness._kill_worker_sigkill() is False
        assert harness._signal_run_process(owned.pid, signal.SIGKILL) is False
        assert _still_alive(owned)  # the run's own process is left alone rather than signalled unsafely
        assert harness.main() == 2
        assert started == []
        assert "pidfd is unavailable" in capsys.readouterr().err
    finally:
        _cleanup_procs(owned, foreign)


def _assert_main_refuses_when_probe_fails(harness, monkeypatch, capsys):
    monkeypatch.setattr(harness, "_PIDFD_SUPPORTED", None)  # force a fresh probe; restored after the test
    started = []
    monkeypatch.setattr(harness, "_start_entrypoint", lambda env: started.append(1))
    assert harness._pidfd_supported() is False
    assert harness.main() == 2
    assert started == []
    assert "pidfd is unavailable" in capsys.readouterr().err


def test_pidfd_probe_fails_closed_when_pidfd_open_is_blocked(monkeypatch, capsys):
    import errno

    harness = _load_harness()

    def blocked(pid, flags=0):
        raise OSError(errno.ENOSYS, "Function not implemented")

    monkeypatch.setattr(harness.os, "pidfd_open", blocked, raising=False)
    _assert_main_refuses_when_probe_fails(harness, monkeypatch, capsys)


def test_pidfd_probe_fails_closed_when_pidfd_send_signal_is_blocked(monkeypatch, capsys):
    import errno

    harness = _load_harness()

    import os

    # pidfd_open is stubbed to succeed so the probe really reaches the signal call on any host,
    # including one without pidfd_open, instead of failing earlier at the open.
    opened, closed, signalled = [], [], []
    real_close = os.close

    def fake_open(pid, flags=0):
        fd = os.open(os.devnull, os.O_RDONLY)
        opened.append(fd)
        return fd

    def spy_close(fd):
        closed.append(fd)
        return real_close(fd)

    def blocked(fd, sig, *a, **k):
        signalled.append((fd, sig))
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(harness.os, "pidfd_open", fake_open, raising=False)
    monkeypatch.setattr(harness.os, "close", spy_close)
    monkeypatch.setattr(harness.signal, "pidfd_send_signal", blocked, raising=False)
    _assert_main_refuses_when_probe_fails(harness, monkeypatch, capsys)
    assert signalled and signalled[0][1] == 0  # the failure came from the signal-0 probe itself
    assert opened and set(opened) <= set(closed)  # and the probe fd was still closed


def _require_real_pidfd():
    """Skip (not fail) before installing a spy on hosts where pidfd is missing or blocked."""
    if _PIDFD_UNAVAILABLE is not None:
        pytest.skip(_PIDFD_UNAVAILABLE)


def _spy_pidfd_fds(harness, monkeypatch):
    opened, closed = [], []
    real_open, real_close = harness.os.pidfd_open, harness.os.close

    def spy_open(pid, flags=0):
        fd = real_open(pid, flags)
        opened.append(fd)
        return fd

    def spy_close(fd):
        closed.append(fd)
        return real_close(fd)

    monkeypatch.setattr(harness.os, "pidfd_open", spy_open)
    monkeypatch.setattr(harness.os, "close", spy_close)
    return opened, closed


def test_pidfd_probe_succeeds_on_this_box_and_closes_its_fd(monkeypatch):
    _require_real_pidfd()
    harness = _load_harness()
    monkeypatch.setattr(harness, "_PIDFD_SUPPORTED", None)
    opened, closed = _spy_pidfd_fds(harness, monkeypatch)
    assert harness._pidfd_supported() is True
    assert opened and closed == opened  # the probe fd is always closed


def test_pidfd_probe_closes_its_fd_when_the_signal_is_blocked(monkeypatch):
    import errno

    _require_real_pidfd()
    harness = _load_harness()
    monkeypatch.setattr(harness, "_PIDFD_SUPPORTED", None)
    opened, closed = _spy_pidfd_fds(harness, monkeypatch)

    def blocked(fd, sig, *a, **k):
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(harness.signal, "pidfd_send_signal", blocked)
    assert harness._pidfd_supported() is False
    assert opened and closed == opened


@requires_real_pidfd
def test_main_exits_2_on_a_keyboard_interrupt_that_leaves_a_process_behind(monkeypatch, capsys):
    harness = _load_harness()
    monkeypatch.setattr(harness, "_start_entrypoint", lambda env: _Proc())
    monkeypatch.setattr(harness, "_wait_http", lambda *a, **k: True)

    def phase(label, *a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(harness, "_phase", phase)
    monkeypatch.setattr(harness, "_stop_entrypoint", lambda proc: None)
    monkeypatch.setattr(harness, "_kill_worker_sigkill", lambda: True)
    monkeypatch.setattr(harness, "_kill_run_processes", lambda token, timeout=15.0: [4242])
    monkeypatch.setattr(harness, "_clear_volume", lambda data_dir: None)
    monkeypatch.setattr(harness.time, "sleep", lambda s: None)

    assert harness.main() == 2
    assert "processes still alive after cleanup: [4242]" in capsys.readouterr().err


@requires_real_pidfd
def test_main_still_propagates_a_keyboard_interrupt_when_the_cleanup_is_clean(monkeypatch):
    harness = _load_harness()
    monkeypatch.setattr(harness, "_start_entrypoint", lambda env: _Proc())
    monkeypatch.setattr(harness, "_wait_http", lambda *a, **k: True)
    monkeypatch.setattr(harness, "_phase", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(harness, "_stop_entrypoint", lambda proc: None)
    monkeypatch.setattr(harness, "_kill_worker_sigkill", lambda: True)
    monkeypatch.setattr(harness, "_kill_run_processes", lambda token, timeout=15.0: [])
    monkeypatch.setattr(harness, "_clear_volume", lambda data_dir: None)
    monkeypatch.setattr(harness.time, "sleep", lambda s: None)

    with pytest.raises(KeyboardInterrupt):
        harness.main()
