#!/usr/bin/env python3
"""Design §7 lifecycle — fly entrypoint, fly.toml env, 3s /api/top-picks polls (F/W/R/C/Z)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import uuid
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
PIDFILE = os.environ.get("INLINE_WORKER_PIDFILE", "/tmp/inline_worker.pid")
RUN_TOKEN_VAR = "S7_HARNESS_RUN_TOKEN"
RUN_TOKEN = uuid.uuid4().hex
# Sessions this run created (one per entrypoint). A process in one of them is ours even when its
# environment cannot be read (non-dumpable processes refuse /proc/<pid>/environ).
_RUN_SESSIONS: set = set()
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
        "INLINE_WORKER_PIDFILE": PIDFILE,
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


def _kill_worker_sigkill() -> bool:
    try:
        pgid = Path(PIDFILE).read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not pgid:
        return False
    try:
        os.kill(int(pgid), signal.SIGKILL)
        return True
    except OSError:
        try:
            os.killpg(int(pgid), signal.SIGKILL)
            return True
        except OSError:
            return False


def _killpg(pgid: int, sig: int) -> None:
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
    _killpg(pgid, signal.SIGTERM)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        pass
    # Web is gone; give the rest of the group (the supervisor subshell) a short grace to exit on the
    # TERM it already has before the KILL.
    deadline = time.monotonic() + STOP_GRACE_SECONDS
    while time.monotonic() < deadline and _group_alive(pgid):
        time.sleep(0.05)
    _killpg(pgid, signal.SIGKILL)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _run_sessions() -> set:
    sessions = set(_RUN_SESSIONS)
    try:
        sessions.add(int(Path(PIDFILE).read_text(encoding="utf-8").strip()))  # the worker's own session
    except (OSError, ValueError):
        pass
    return sessions


def _run_pids(token: str) -> List[int]:
    """Pids of live (non-zombie) processes that belong to this run.

    A process belongs to the run when its environment carries the run token, or, when that
    environment cannot be read (a non-dumpable process refuses ``/proc/<pid>/environ``), when it sits
    in a session this run created. Unreadable processes outside those sessions cannot be attributed
    and are ignored: on a shared box other users' (and sandboxed) processes are always unreadable,
    so treating every one as ours would make the check unsatisfiable.
    """
    needle = f"{RUN_TOKEN_VAR}={token}".encode()
    me = os.getpid()
    sessions = _run_sessions()
    found: List[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[-1].split()
        except OSError:
            continue
        try:
            ours = needle in (entry / "environ").read_bytes().split(b"\0")
        except PermissionError:
            ours = int(fields[3]) in sessions
        except OSError:
            continue
        if ours and fields[0] != "Z":
            found.append(int(entry.name))
    return found


def _kill_run_processes(token: str, timeout: float = 15.0) -> List[int]:
    """SIGKILL every process this run started and wait for them to go; return any survivors.

    The supervisor may have launched a worker whose pid was not yet in the pidfile when the
    supervisor died, so the pidfile alone cannot be trusted to find every worker.
    """
    deadline = time.monotonic() + timeout
    while True:
        pids = _run_pids(token)
        if not pids:
            return []
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        if time.monotonic() >= deadline:
            return _run_pids(token)
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
    port = os.environ.get("HARNESS_PORT", "18080")
    base = f"http://127.0.0.1:{port}"
    seed_default = str(REPO / "data_seeds" / "score_snapshots.json")
    results: List[PhaseResult] = []
    phase_states: Dict[str, List[str]] = {}
    f_volume_day_rows: Optional[int] = None

    with tempfile.TemporaryDirectory(prefix="s7-") as tmp:
        data_dir = Path(tmp)
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
                print(f"WARNING: processes still alive after cleanup: {leftover}", file=sys.stderr)

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
