#!/usr/bin/env python3
"""Design §7 lifecycle — fly entrypoint, fly.toml env, 3s /api/top-picks polls (F/W/R/C/Z)."""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import uuid
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
# The worker pid file of THIS run. ``main`` points it into the run's temporary data directory; it must
# never be the shared /tmp/inline_worker.pid (or an inherited INLINE_WORKER_PIDFILE), which may belong to
# another entrypoint whose live worker the new entrypoint would adopt and the harness would then kill.
PIDFILE = os.environ.get("INLINE_WORKER_PIDFILE", "/tmp/inline_worker.pid")
RUN_TOKEN_VAR = "S7_HARNESS_RUN_TOKEN"
RUN_TOKEN = uuid.uuid4().hex
# Sessions this run created (one per entrypoint). They are used to REPORT a live process whose
# environment cannot be read (non-dumpable processes refuse /proc/<pid>/environ); such a process is
# never signalled, because a dead entrypoint's pid can be recycled by an unrelated session leader and
# membership of a recorded session id is then not proof of ownership.
_RUN_SESSIONS: set = set()
# Pids still alive after the final cleanup of ``_run``: the run cannot be called a success then.
_CLEANUP_SURVIVORS: List[int] = []
STOP_GRACE_SECONDS = 3.0


@dataclass
class PhaseResult:
    phase: str
    polls: int
    empty: int
    unreachable: int
    last_state: str
    volume_bytes: int


def _poll(base: str, timeout: float = 2.5) -> Dict[str, Any]:
    url = f"{base.rstrip('/')}/api/top-picks"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return {}


def _empty(body: Dict[str, Any]) -> bool:
    return not (body.get("day_picks") or body.get("hour_picks"))


def _state(body: Dict[str, Any]) -> str:
    meta = body.get("meta") or {}
    return str(meta.get("snapshot_state") or meta.get("fallback_status") or "")


def _phase(
    label: str,
    base: str,
    seconds: float,
    snapshots_path: Path,
    interval: float = 3.0,
) -> tuple[PhaseResult, List[str]]:
    polls = empty = unreachable = 0
    last = ""
    states_seen: List[str] = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        polls += 1
        body = _poll(base)
        if not body:
            unreachable += 1
        elif _empty(body):
            empty += 1
        else:
            st = _state(body)
            if st and (not states_seen or states_seen[-1] != st):
                states_seen.append(st)
            last = st or last
        time.sleep(interval)
    vbytes = snapshots_path.stat().st_size if snapshots_path.is_file() else 0
    return PhaseResult(label, polls, empty, unreachable, last, vbytes), states_seen


def _fly_env(data_dir: Path, port: str, *, seed_path: str) -> Dict[str, str]:
    return {
        **os.environ,
        "DATA_DIR": str(data_dir),
        "DISABLE_BACKGROUND_SCANS": "1",
        "PORT": port,
        "BOOT_DEFER_SECONDS": os.environ.get("BOOT_DEFER_SECONDS", "90"),
        "SCORE_SNAPSHOT_BOOT_IMMEDIATE": os.environ.get("SCORE_SNAPSHOT_BOOT_IMMEDIATE", "on"),
        "SCORE_SNAPSHOT_FIRST_DELAY_SECONDS": os.environ.get("SCORE_SNAPSHOT_FIRST_DELAY_SECONDS", "30"),
        "PICK_HANDLER_TIMEOUT_SECONDS": os.environ.get("PICK_HANDLER_TIMEOUT_SECONDS", "8"),
        "SCORE_SNAPSHOT_SCHEDULER_ENABLED": "on",
        "SCORE_SNAPSHOT_REGISTRY_ONLY": "on",
        "SCORE_SNAPSHOT_SCORE_WORKERS": "1",
        "SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS": os.environ.get(
            "SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS", "120"
        ),
        "SCORE_SNAPSHOT_REFRESH_MINUTES": os.environ.get("SCORE_SNAPSHOT_REFRESH_MINUTES", "10"),
        "ENABLE_INLINE_WORKER": "1",
        "WORKER_HEAVY": "essential",
        "RUN_MODE": "web",
        "SCORE_SNAPSHOTS_PATH": str(data_dir / "score_snapshots.json"),
        "SCORE_SNAPSHOT_SEED_PATH": seed_path,
        "SCORE_SNAPSHOT_CYCLE_PATH": str(data_dir / "score_snapshot_cycle.json"),
        "INLINE_WORKER_PIDFILE": str(data_dir / "inline_worker.pid"),
        "PYTHONPATH": str(REPO),
        # Every process this run starts (web, worker supervisor, worker) inherits this, so the
        # harness can find them all again by environment, however many sessions they moved to.
        RUN_TOKEN_VAR: RUN_TOKEN,
    }


def _start_entrypoint(env: Dict[str, str]) -> subprocess.Popen:
    proc = subprocess.Popen(
        ["sh", str(REPO / "scripts" / "fly_web_entrypoint.sh")],
        cwd=str(REPO),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        # Own session: the entrypoint, its worker-supervisor subshell and the web process it execs
        # into share one process group the harness can signal as a unit.
        start_new_session=True,
    )
    _RUN_SESSIONS.add(proc.pid)
    return proc


def _wait_http(base: str, timeout: float = 120.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _poll(base):
            return True
        time.sleep(1.0)
    return False


def _worker_pid_from_pidfile() -> Optional[int]:
    try:
        return int(Path(PIDFILE).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _carries_run_token(pid: int, token: Optional[str] = None) -> bool:
    """True only when ``pid``'s environment carries the run token (a READ, not a licence to signal).

    An unreadable environment is not proof. Never signal a pid on the strength of this alone: between
    this read and a ``kill`` the process can exit and its pid be reused. Signal through
    ``_signal_run_process`` instead, which holds a pidfd across the check and the signal.
    """
    needle = f"{RUN_TOKEN_VAR}={RUN_TOKEN if token is None else token}".encode()
    try:
        return needle in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except OSError:
        return False


_PIDFD_SUPPORTED: Optional[bool] = None


def _pidfd_supported() -> bool:
    """True when this kernel and Python can open a pidfd and signal through it (Linux 5.3+, Python 3.9+)."""
    global _PIDFD_SUPPORTED
    if _PIDFD_SUPPORTED is None:
        try:
            fd = os.pidfd_open(os.getpid())
            os.close(fd)
            _PIDFD_SUPPORTED = hasattr(signal, "pidfd_send_signal")
        except (AttributeError, OSError):
            _PIDFD_SUPPORTED = False
    return _PIDFD_SUPPORTED


def _open_run_pidfd(pid: int, token: Optional[str] = None) -> Optional[int]:
    """A pidfd for ``pid`` if, while holding it, the process provably carries this run's token.

    The pidfd names one process for as long as it is open, even if that process exits and its pid is
    reused. The token is read from ``/proc/<pid>`` after the pidfd is open, and the pidfd must still be
    alive afterwards (a pidfd turns readable when its process exits): a pid cannot be recycled while its
    process exists, so the environment that was read is that process's. The caller closes the fd.
    Returns None (and signals nothing) when the process is not provably the run's or pidfd is
    unavailable.
    """
    if not _pidfd_supported() or pid <= 1 or pid == os.getpid():
        return None
    try:
        fd = os.pidfd_open(pid)
    except OSError:
        return None
    try:
        if _carries_run_token(pid, token) and not select.select([fd], [], [], 0)[0]:
            return fd
    except OSError:
        pass
    os.close(fd)
    return None


def _signal_run_process(pid: int, sig: int, token: Optional[str] = None) -> bool:
    """Signal ``pid`` only if it provably belongs to this run, with no check-then-signal window.

    Check and signal use the same pidfd, so a process that exits and has its pid reused in between
    cannot receive the signal. Never signals by raw pid; without pidfd support it signals nothing.
    """
    fd = _open_run_pidfd(pid, token)
    if fd is None:
        return False
    try:
        signal.pidfd_send_signal(fd, sig)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def _kill_worker_sigkill() -> bool:
    """SIGKILL the worker named in this run's pid file, but only if it carries this run's token.

    Only the worker itself is signalled (through a pidfd); anything else it started carries the token
    too and is stopped by the run-token sweep in ``_kill_run_processes``.
    """
    pid = _worker_pid_from_pidfile()
    if pid is None:
        return False
    return _signal_run_process(pid, signal.SIGKILL)


def _killpg(pgid: int, sig: int) -> None:
    """Signal a process group by id. Only for the group of an entrypoint leader that this run has not
    reaped yet (``Popen.poll()`` is None): an unreaped leader, even a zombie, keeps its pid, so the group
    id cannot name anyone else. Everything else goes through ``_signal_run_process``."""
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _stop_entrypoint(proc: subprocess.Popen) -> None:
    """Stop web *and* the worker supervisor.

    ``fly_web_entrypoint.sh`` forks a supervisor subshell that restarts the inline worker, then execs
    web. SIGTERM to the web pid alone leaves that supervisor running, so it signals the whole group
    and then SIGKILLs whatever is left of it. The worker itself runs under ``setsid`` in its own
    group and is stopped separately (``_kill_worker_sigkill`` / ``_kill_run_processes``).
    """
    pgid = proc.pid
    if proc.poll() is None:
        _killpg(pgid, signal.SIGTERM)  # the leader is not reaped yet, so the group id is still ours
    else:
        # Already reaped: the pid may have been recycled since, so signal only members that carry
        # this run's token.
        _signal_group_members(pgid, signal.SIGTERM)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        pass
    # Web is gone; give the rest of the group (the supervisor subshell) a short grace to exit on the
    # TERM it already has before the KILL.
    deadline = time.monotonic() + STOP_GRACE_SECONDS
    while time.monotonic() < deadline and _group_alive(pgid):
        time.sleep(0.05)
    if proc.poll() is None:
        _killpg(pgid, signal.SIGKILL)
    else:
        # The leader is gone, so ``pgid`` may by now name an unrelated group: SIGKILL only the members
        # that provably carry this run's token. Anything unreadable is left alone (and reported by
        # ``_kill_run_processes``).
        _signal_group_members(pgid, signal.SIGKILL)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _group_members(pgid: int) -> List[int]:
    members: List[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[-1].split()
        except OSError:
            continue
        if int(fields[2]) == pgid and fields[0] != "Z":
            members.append(int(entry.name))
    return members


def _signal_group_members(pgid: int, sig: int) -> None:
    """Signal each live member of group ``pgid`` that provably carries this run's token (via pidfd)."""
    me = os.getpid()
    for pid in _group_members(pgid):
        if pid != me:
            _signal_run_process(pid, sig)


def _group_alive(pgid: int) -> bool:
    """True while a non-zombie process is in process group ``pgid``.

    A zombie (state Z) is already dead and only waits to be reaped by its parent; where nothing reaps
    orphans (a container without an init) it would stay in the group forever, so ``killpg(pgid, 0)``
    cannot be used: it counts zombies.
    """
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[-1].split()
        except OSError:
            continue
        if int(fields[2]) == pgid and fields[0] != "Z":
            return True
    return False


def _run_sessions() -> set:
    sessions = set(_RUN_SESSIONS)
    worker = _worker_pid_from_pidfile()
    if worker is not None and _carries_run_token(worker):
        sessions.add(worker)  # the worker's own session (only a verified worker: never a foreign pid)
    return sessions


def _scan_run_processes(token: str) -> Tuple[List[int], List[int]]:
    """Live (non-zombie) processes of this run: ``(proven, unattributable)``.

    ``proven``: the environment carries the run token. Only these are ever signalled.
    ``unattributable``: the environment cannot be read (a non-dumpable process refuses
    ``/proc/<pid>/environ``) but the process sits in a session this run created. It is never signalled,
    since the session id of a dead entrypoint can be recycled by an unrelated process and "in a session
    we once created" is then not proof; it is only reported, so a cleanup that leaves one behind fails
    loudly instead of killing something that may not be ours. Unreadable processes outside those
    sessions are not reported: on a shared box other users' (and sandboxed) processes are unreadable.
    """
    needle = f"{RUN_TOKEN_VAR}={token}".encode()
    me = os.getpid()
    sessions = _run_sessions()
    proven: List[int] = []
    unattributable: List[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[-1].split()
        except OSError:
            continue
        if fields[0] == "Z":
            continue
        try:
            if needle in (entry / "environ").read_bytes().split(b"\0"):
                proven.append(int(entry.name))
        except PermissionError:
            if int(fields[3]) in sessions:
                unattributable.append(int(entry.name))
        except OSError:
            continue
    return proven, unattributable


def _run_pids(token: str) -> List[int]:
    """Pids of live processes that provably belong to this run (they carry its token)."""
    return _scan_run_processes(token)[0]


def _unattributable_run_pids(token: str) -> List[int]:
    """Live processes in this run's sessions whose environment cannot be read: reported, never killed."""
    return _scan_run_processes(token)[1]


def _kill_run_processes(token: str, timeout: float = 15.0) -> List[int]:
    """SIGKILL every process that provably carries this run's token and wait for them to go.

    Returns the survivors: token-bearing processes that would not die, plus live processes of this
    run's sessions whose environment is unreadable (those are never signalled, only reported).

    The supervisor may have launched a worker whose pid was not yet in the pidfile when the
    supervisor died, so the pidfile alone cannot be trusted to find every worker.
    """
    deadline = time.monotonic() + timeout
    while True:
        pids = _run_pids(token)
        if not pids:
            return _unattributable_run_pids(token)
        for pid in pids:
            _signal_run_process(pid, signal.SIGKILL, token)
        if time.monotonic() >= deadline:
            return _run_pids(token) + _unattributable_run_pids(token)
        time.sleep(0.1)


def _clear_volume(data_dir: Path) -> None:
    """Remove the volume snapshot and the producer receipt (the state a cold volume lacks).

    The ``.lock`` file stays: it is synchronisation metadata, not volume state. ``_locked_score_snapshot``
    opens it append-mode and ``flock``s the inode, so unlinking it while a writer still holds the old
    inode lets a later writer lock a fresh inode that does not contend with it.
    """
    volume = data_dir / "score_snapshots.json"
    for path in (volume, data_dir / "score_snapshot_cycle.json"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _stop_run() -> List[int]:
    """Stop everything this run started (web, supervisor, worker); return survivors.

    ``_stop_entrypoint`` only covers the web/supervisor group; the worker runs in its own session,
    so it is killed here and the run token is swept until nothing is left.
    """
    _kill_worker_sigkill()
    return _kill_run_processes(RUN_TOKEN)


def main() -> int:
    """Run the lifecycle; exit 2 when a process of the run survives the final cleanup."""
    _CLEANUP_SURVIVORS.clear()
    if not _pidfd_supported():
        # Every cleanup signal goes through a pidfd (no check-then-signal pid reuse window). Without
        # one the harness could not stop its processes safely, so it refuses to start any.
        print("FATAL: pidfd is unavailable (needs Linux 5.3+ and Python 3.9+); not starting anything", file=sys.stderr)
        return 2
    try:
        code = _run()
    except BaseException:  # includes KeyboardInterrupt: an interrupted run must still report a survivor
        # A phase raised. If the cleanup in ``_run``'s ``finally`` also left a process behind, that is
        # the verdict (exit 2, with the traceback shown); otherwise the exception propagates unchanged.
        if not _CLEANUP_SURVIVORS:
            raise
        traceback.print_exc()
        code = 2
    if _CLEANUP_SURVIVORS:
        print(f"FATAL: processes still alive after cleanup: {sorted(set(_CLEANUP_SURVIVORS))}", file=sys.stderr)
        return 2
    return code


def _run() -> int:
    global PIDFILE
    port = os.environ.get("HARNESS_PORT", "18080")
    base = f"http://127.0.0.1:{port}"
    seed_default = str(REPO / "data_seeds" / "score_snapshots.json")
    results: List[PhaseResult] = []
    phase_states: Dict[str, List[str]] = {}
    f_volume_day_rows: Optional[int] = None

    with tempfile.TemporaryDirectory(prefix="s7-") as tmp:
        data_dir = Path(tmp)
        PIDFILE = str(data_dir / "inline_worker.pid")
        snapshots_path = data_dir / "score_snapshots.json"
        env = _fly_env(data_dir, port, seed_path=seed_default)
        proc = None
        try:
            proc = _start_entrypoint(env)
            if not _wait_http(base, timeout=120):
                print("FATAL: HTTP never became ready", file=sys.stderr)
                return 2
            f_row, f_states = _phase(
                "F",
                base,
                float(os.environ.get("PHASE_F_SECONDS", "420")),
                snapshots_path,
            )
            results.append(f_row)
            phase_states["F"] = f_states
            if snapshots_path.is_file():
                try:
                    snap = json.loads(snapshots_path.read_text(encoding="utf-8"))
                    f_volume_day_rows = len(snap.get("day") or [])
                except (OSError, json.JSONDecodeError):
                    f_volume_day_rows = None
            _kill_worker_sigkill()
            w_row, w_states = _phase(
                "W",
                base,
                float(os.environ.get("PHASE_W_SECONDS", "60")),
                snapshots_path,
            )
            results.append(w_row)
            phase_states["W"] = w_states
            _stop_entrypoint(proc)
            proc.wait(timeout=10)
            time.sleep(3)
            proc = _start_entrypoint(env)
            if not _wait_http(base, timeout=120):
                return 2
            r_row, r_states = _phase(
                "R",
                base,
                float(os.environ.get("PHASE_R_SECONDS", "30")),
                snapshots_path,
            )
            results.append(r_row)
            phase_states["R"] = r_states

            env_c = dict(env)
            env_c["FINNEY_RPC_URL"] = "http://127.0.0.1:9"
            env_c["BLOCKMACHINE_RPC_URL"] = "http://127.0.0.1:9"
            env_c["PICK_HANDLER_TIMEOUT_SECONDS"] = "0.001"
            # C changes the environment (RPC outage), so the worker must be restarted under it: a
            # worker left running would be reused through the pidfile with the old environment.
            _stop_entrypoint(proc)
            proc.wait(timeout=10)
            survivors = _stop_run()
            if survivors:
                print(f"FATAL: processes still alive before phase C: {survivors}", file=sys.stderr)
                return 2
            time.sleep(2)
            proc = _start_entrypoint(env_c)
            if not _wait_http(base, timeout=120):
                return 2
            c_row, c_states = _phase(
                "C",
                base,
                float(os.environ.get("PHASE_C_SECONDS", "40")),
                snapshots_path,
            )
            results.append(c_row)
            phase_states["C"] = c_states

            env_z = _fly_env(data_dir, port, seed_path=str(data_dir / "missing_seed.json"))
            _stop_entrypoint(proc)
            proc.wait(timeout=10)
            # _stop_entrypoint ended web and the worker supervisor; the worker (own session) is
            # killed here and every process of this run is confirmed dead before the volume is
            # touched, so nothing can restart and refill it before the cold-start check.
            survivors = _stop_run()
            if survivors:
                print(f"FATAL: processes still alive before phase Z: {survivors}", file=sys.stderr)
                return 2
            time.sleep(2)
            # Z is the cold start with no volume and no seed: drop what F/W/R/C built, or the
            # volume snapshot would still be served and the case would never run.
            _clear_volume(data_dir)
            proc = _start_entrypoint(env_z)
            if not _wait_http(base, timeout=90):
                return 2
            z_row, z_states = _phase(
                "Z",
                base,
                float(os.environ.get("PHASE_Z_SECONDS", "60")),
                snapshots_path,
            )
            results.append(z_row)
            phase_states["Z"] = z_states
        finally:
            # Success, early return or exception: nothing of this run may outlive the data dir.
            if proc is not None:
                _stop_entrypoint(proc)
            leftover = _stop_run()
            if leftover:
                _CLEANUP_SURVIVORS.extend(leftover)

    print("| Phase | polls | empty | unreachable | served_states | volume_bytes |")
    print("|---|---:|---:|---:|---|---:|")
    for row in results:
        served = "→".join(phase_states.get(row.phase) or []) or row.last_state
        print(
            f"| {row.phase} | {row.polls} | {row.empty} | {row.unreachable} | "
            f"{served} | {row.volume_bytes} |"
        )
    f_row = next((r for r in results if r.phase == "F"), None)
    z_row = next((r for r in results if r.phase == "Z"), None)
    ok = True
    for row in results:
        if row.phase == "Z":
            if row.unreachable > 0:
                print(f"FAIL: {row.phase} unreachable={row.unreachable}", file=sys.stderr)
                ok = False
            continue
        if row.empty > 0 or row.unreachable > 0:
            print(
                f"FAIL: {row.phase} empty={row.empty} unreachable={row.unreachable}",
                file=sys.stderr,
            )
            ok = False
    f_states = phase_states.get("F") or []
    if "seed" not in f_states or "fresh" not in f_states:
        print(f"FAIL: F served_states={f_states!r} (need seed→fresh)", file=sys.stderr)
        ok = False
    if f_volume_day_rows != 128:
        print(f"FAIL: F_volume_day_rows={f_volume_day_rows} (need 128)", file=sys.stderr)
        ok = False
    elif f_row and f_row.volume_bytes < 100:
        print(f"FAIL: F volume_bytes={f_row.volume_bytes}", file=sys.stderr)
        ok = False
    else:
        print(f"F_volume_day_rows={f_volume_day_rows}", file=sys.stderr)
    if z_row and z_row.empty < 1:
        print("WARN: Z expected some empty polls without seed", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
