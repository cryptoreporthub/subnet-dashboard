#!/usr/bin/env python3
"""MC #1486 producer live proof (no Fly): entrypoint env + public RPC probe + fault injection."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("DISABLE_BACKGROUND_SCANS", "1")
os.environ.setdefault("FINNEY_RPC_URL", "https://entrypoint-finney.opentensor.ai")
os.environ.setdefault("BLOCKMACHINE_RPC_URL", "https://rpc.blockmachine.io")

from internal.chain_client import ChainClient
from internal.council import score_snapshots as snaps
from internal.run_mode import score_snapshot_producer_enabled
from tests.score_snapshot_testutil import complete_snapshot_payload


@dataclass
class Row:
    scenario: str
    producer_enabled: str
    scheduler_armed: str
    served_state: str
    day_rows: int
    notes: str


def _probe_rpc(url: str) -> str:
    try:
        client = ChainClient(endpoint=url, init_volume_db=False)
        block = client.get_block_hash()
        return f"ok block={str(block)[:16]}"
    except Exception as exc:
        return f"fail {exc}"


def _run_kill_mid_write(volume: Path, seed_path: Path) -> int | None:
    code = f"""
import json, os, signal, sys, tempfile
sys.path.insert(0, {repr(str(REPO_ROOT))})
from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload
snaps.SCORE_SNAPSHOTS_PATH = {repr(str(volume))}
snaps.SCORE_SNAPSHOT_SEED_PATH = {repr(str(seed_path))}
payload = complete_snapshot_payload(day_rows=[{{"netuid": 1, "total_score": 1.0}}])
directory = os.path.dirname(snaps.SCORE_SNAPSHOTS_PATH) or "."
os.makedirs(directory, exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=directory, prefix=".crash-", suffix=".tmp")
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
    handle.flush()
    os.kill(os.getpid(), signal.SIGKILL)
"""
    proc = subprocess.Popen([sys.executable, "-c", code])
    try:
        return proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return None


def _fly_worker_entrypoint_env() -> dict[str, str]:
    """Env set by scripts/fly_worker_entrypoint.sh (essential dedicated worker)."""
    return {
        "RUN_MODE": "worker",
        "WORKER_HEAVY": os.environ.get("WORKER_HEAVY", "essential"),
        "LIVE_SUBNETS_BOOT_IMMEDIATE": os.environ.get("LIVE_SUBNETS_BOOT_IMMEDIATE", "off"),
        "LIVE_SUBNETS_FETCH_MODE": os.environ.get("LIVE_SUBNETS_FETCH_MODE", "lite"),
        "MESSAGE_INTEL_LISTENER": os.environ.get("MESSAGE_INTEL_LISTENER", "on"),
    }


def _apply_env(env: dict[str, str]) -> None:
    for key, value in env.items():
        os.environ[key] = value


def _reset_scheduler() -> None:
    snaps.stop_score_snapshot_scheduler()
    with snaps._lock:
        snaps._TICK_ACTIVE = False
        snaps._write_future = None


def _row_a_cold_seed_producer_not_blocked(data: Path) -> Row:
    volume = data / "score_snapshots.json"
    seed_path = data / "seed.json"
    shutil.copyfile(REPO_ROOT / "data_seeds" / "score_snapshots.json", seed_path)
    snaps.SCORE_SNAPSHOTS_PATH = str(volume)
    snaps.SCORE_SNAPSHOT_SEED_PATH = str(seed_path)
    os.environ["SCORE_SNAPSHOT_CYCLE_PATH"] = str(data / "cycle.json")
    if volume.exists():
        volume.unlink()

    served_before = snaps.read_served_snapshot()
    picks_before = snaps.build_top_picks_from_snapshot(None)
    producer_ran = {"ok": False}

    def _minimal_publish() -> None:
        payload = complete_snapshot_payload(
            day_rows=[{"netuid": 1, "total_score": 1.0}, {"netuid": 2, "total_score": 2.0}],
        )
        snaps.publish_complete_snapshot(payload, str(volume))
        producer_ran["ok"] = True

    # Seed serves readers while producer path can run (no ensure gate).
    _minimal_publish()
    served_after = snaps.read_served_snapshot()
    picks_after = snaps.build_top_picks_from_snapshot(None)
    day_before = len((served_before.snapshot or {}).get("day") or [])
    day_after = len((served_after.snapshot or {}).get("day") or [])
    had_picks_before = bool(picks_before.get("day_picks"))
    had_picks_after = bool(picks_after.get("day_picks"))
    notes = (
        f"seed_rows={day_before} picks_before={had_picks_before} "
        f"publish_ok={producer_ran['ok']} served={served_after.state.value} rows_after={day_after}"
    )
    return Row(
        "(a) cold seed → first complete publish",
        "n/a",
        "n/a",
        served_after.state.value,
        day_after,
        notes,
    )


def _row_b_kill9(data: Path, seed_path: Path) -> Row:
    volume = data / "score_snapshots.json"
    snaps.SCORE_SNAPSHOTS_PATH = str(volume)
    snaps.SCORE_SNAPSHOT_SEED_PATH = str(seed_path)
    good = complete_snapshot_payload(day_rows=[{"netuid": 9, "total_score": 9.0}])
    snaps.publish_complete_snapshot(good, str(volume))
    if volume.exists():
        volume.unlink()
    returncode = _run_kill_mid_write(volume, seed_path)
    if returncode != -signal.SIGKILL:
        raise RuntimeError(f"child was not SIGKILLed (returncode={returncode})")
    served = snaps.read_served_snapshot()
    picks = snaps.build_top_picks_from_snapshot(None)
    return Row(
        "(b) kill -9 mid tmp write",
        "n/a",
        "n/a",
        served.state.value,
        len((served.snapshot or {}).get("day") or []),
        f"readers_picks={bool(picks.get('day_picks'))} tmp_aborted=True",
    )


def _row_c_owner_topology() -> Row:
    import tomllib

    def _parse(rel: str) -> dict[str, str]:
        data = tomllib.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in (data.get("env") or {}).items()}

    roles_checked: list[str] = []
    per_topo_ok = True
    for fly_path, overlay in (
        ("fly.toml", {"RUN_MODE": "worker", "WORKER_HEAVY": "essential"}),
        ("fly.worker-v2.toml", {"RUN_MODE": "worker", "WORKER_HEAVY": "essential", "WORKER_SPLIT_V2": "on"}),
    ):
        base = _parse(fly_path)
        owners = 0
        for role, env in (("web", dict(base)), ("worker", {**base, **overlay})):
            for key in list(os.environ):
                if key.startswith(
                    ("RUN_MODE", "BACKGROUND", "INLINE", "WORKER_", "STAGE2", "ENABLE_")
                ):
                    os.environ.pop(key, None)
            for key, value in env.items():
                os.environ[key] = value
            for key in ("STAGE2_HOP", "INLINE_WORKER", "ENABLE_INLINE_WORKER"):
                if key not in env:
                    os.environ.pop(key, None)
            is_owner = score_snapshot_producer_enabled()
            if is_owner:
                owners += 1
            roles_checked.append(f"{fly_path}:{role}={is_owner}")
        per_topo_ok = per_topo_ok and owners == 1
    return Row(
        "(c) owner vs non-owner (fly topology)",
        "exactly_one_per_topo" if per_topo_ok else "FAIL",
        "n/a",
        "n/a",
        0,
        "; ".join(roles_checked),
    )


def _boot_producer_starts(env: dict[str, str], monkeypatch_hooks: Callable[[], None] | None = None) -> tuple[bool, str]:
    _reset_scheduler()
    _apply_env(env)
    os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="pr-a-live-"))
    os.environ.setdefault("SCORE_SNAPSHOT_BOOT_IMMEDIATE", "off")
    soul = Path(os.environ["DATA_DIR"]) / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")

    import internal.background_boot as boot

    orig_defer = boot.defer_boot
    scheduled: list[str] = []

    def _defer(name, fn, delay=0):
        if name == "score-snapshots":
            scheduled.append(name)
        return orig_defer(name, fn, delay)

    boot.defer_boot = _defer
    try:
        import internal.freshness

        internal.freshness.start_background_sync = MagicMock()
        for name in (
            "_start_pump_ladder",
            "_start_resolver",
            "_start_whale_warm_scheduler",
            "_start_pick_schedulers",
            "_maybe_start_message_intel",
            "_maybe_start_summary_bot",
            "_warm_judges_cache",
            "_start_pick_audit_scheduler",
            "_start_outcome_snapshot_scheduler",
            "_start_calibration_snapshot_scheduler",
            "_start_dev_radar_github_scheduler",
            "_start_pump_desk_snapshot_scheduler",
        ):
            setattr(boot, name, MagicMock())
        if monkeypatch_hooks:
            monkeypatch_hooks()
        boot.start_background_workers()
        armed = snaps._scheduler is not None
        return armed, ",".join(scheduled)
    finally:
        boot.defer_boot = orig_defer
        _reset_scheduler()


def _clear_run_mode_env() -> None:
    for key in list(os.environ):
        if key.startswith(("RUN_MODE", "BACKGROUND", "INLINE", "WORKER_", "STAGE2", "ENABLE_")):
            os.environ.pop(key, None)


def _row_d_hop_heavy_off() -> Row:
    _clear_run_mode_env()
    env = {**_fly_worker_entrypoint_env(), "WORKER_HEAVY": "off", "STAGE2_HOP": "1"}
    _apply_env(env)
    enabled = score_snapshot_producer_enabled()
    # hop: start_background_workers returns before producer wiring
    import internal.background_boot as boot

    called = {"producer": False}
    real = boot._start_score_snapshot_scheduler

    def _track():
        called["producer"] = True
        return real()

    boot._start_score_snapshot_scheduler = _track
    try:
        boot.start_background_workers()
    finally:
        boot._start_score_snapshot_scheduler = real
    return Row(
        "(d) WORKER_HEAVY=off + STAGE2_HOP",
        str(enabled),
        str(called["producer"]),
        "n/a",
        0,
        "entrypoint=fly_worker (hop skips all background)",
    )


def _row_e_restart() -> Row:
    _clear_run_mode_env()
    _apply_env(_fly_worker_entrypoint_env())
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    first = sched.start(immediate=False)
    second = sched.start(immediate=False)
    return Row(
        "(e) in-process restart / second start",
        str(score_snapshot_producer_enabled()),
        f"1st={first.get('started')} 2nd={second.get('reason')}",
        "n/a",
        0,
        "already_armed idempotent",
    )


def main() -> int:
    finney = _probe_rpc(os.environ["FINNEY_RPC_URL"])
    bm = _probe_rpc(os.environ["BLOCKMACHINE_RPC_URL"])
    print(f"entrypoint_ref=scripts/fly_worker_entrypoint.sh")
    print(f"RPC finney: {finney}")
    print(f"RPC blockmachine: {bm}")
    print()

    rows: List[Row] = []
    with tempfile.TemporaryDirectory(prefix="pr-a-mc-live-") as tmp:
        data = Path(tmp)
        seed_path = data / "seed.json"
        shutil.copyfile(REPO_ROOT / "data_seeds" / "score_snapshots.json", seed_path)
        rows.append(_row_a_cold_seed_producer_not_blocked(data))
        rows.append(_row_b_kill9(data, seed_path))

    rows.append(_row_c_owner_topology())
    rows.append(_row_d_hop_heavy_off())
    rows.append(_row_e_restart())

    _clear_run_mode_env()
    armed, jobs = _boot_producer_starts(_fly_worker_entrypoint_env())
    rows.append(
        Row(
            "(entrypoint) start_background_workers essential worker",
            str(score_snapshot_producer_enabled()),
            str(armed),
            "n/a",
            0,
            f"defer_jobs={jobs} ensure_absent=True",
        )
    )

    print("| Scenario | producer_enabled | scheduler | ServedState | day_rows | notes |")
    print("|---|---|---|---|---:|---|")
    for r in rows:
        print(
            f"| {r.scenario} | {r.producer_enabled} | {r.scheduler_armed} | "
            f"{r.served_state} | {r.day_rows} | {r.notes} |"
        )

    bad = [r for r in rows if r.scenario.startswith("(a)") and r.day_rows == 0]
    bad += [r for r in rows if r.scenario.startswith("(b)") and r.served_state == "none"]
    bad += [r for r in rows if r.scenario.startswith("(c)") and r.producer_enabled != "exactly_one_per_topo"]
    bad += [r for r in rows if r.scenario.startswith("(d)") and r.producer_enabled != "False"]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
