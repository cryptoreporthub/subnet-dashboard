#!/usr/bin/env python3
"""Emit MC lifecycle proof table (public Finney + Blockmachine RPC probe, local data dir)."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("DISABLE_BACKGROUND_SCANS", "1")
os.environ.setdefault("FINNEY_RPC_URL", "https://entrypoint-finney.opentensor.ai")
os.environ.setdefault("BLOCKMACHINE_RPC_URL", "https://rpc.blockmachine.io")

from internal.chain_client import ChainClient
from internal.council import score_snapshots as snaps
from internal.council.scorer_identity import SCORER_REVISION, current_scorer_digest
from tests.score_snapshot_testutil import complete_snapshot_payload


@dataclass
class Row:
    scenario: str
    served_state: str
    row_count: int
    scorer_revision: Any
    scorer_digest: str
    empty_polls: int


def _probe_rpc(url: str) -> str:
    try:
        client = ChainClient(endpoint=url, init_volume_db=False)
        block = client.get_block_hash()
        return f"ok block={str(block)[:16]}"
    except Exception as exc:
        return f"fail {exc}"


def _empty_polls_until_picks(fn: Callable[[], Any], max_tries: int = 5) -> tuple[int, Any]:
    polls = 0
    last = None
    for _ in range(max_tries):
        last = fn()
        picks = last if isinstance(last, dict) else {}
        if picks.get("day_picks") or picks.get("hour_picks"):
            return polls, last
        polls += 1
    return polls, last


def _row_from_served(scenario: str, empty_polls: int) -> Row:
    served = snaps.read_served_snapshot()
    snap = served.snapshot or {}
    day = snap.get("day") or []
    return Row(
        scenario=scenario,
        served_state=served.state.value,
        row_count=len(day),
        scorer_revision=snap.get("scorer_revision"),
        scorer_digest=str(snap.get("scorer_digest") or ""),
        empty_polls=empty_polls,
    )


def _run_kill_mid_write(volume: Path, seed_path: Path) -> None:
    """Child process killed during tmp write (fault injection)."""
    code = f"""
import json, os, signal, sys, time
sys.path.insert(0, {repr(str(REPO_ROOT))})
from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload
snaps.SCORE_SNAPSHOTS_PATH = {repr(str(volume))}
snaps.SCORE_SNAPSHOT_SEED_PATH = {repr(str(seed_path))}
payload = complete_snapshot_payload(day_rows=[{{"netuid": 1, "total_score": 1.0}}])
directory = os.path.dirname(snaps.SCORE_SNAPSHOTS_PATH) or "."
os.makedirs(directory, exist_ok=True)
tmp = os.path.join(directory, ".crash.tmp")
with open(tmp, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
    handle.flush()
    os.kill(os.getpid(), signal.SIGKILL)
"""
    proc = subprocess.Popen([sys.executable, "-c", code])
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def main() -> int:
    finney_status = _probe_rpc(os.environ["FINNEY_RPC_URL"])
    bm_status = _probe_rpc(os.environ["BLOCKMACHINE_RPC_URL"])
    print(f"RPC probe finney: {finney_status}")
    print(f"RPC probe blockmachine: {bm_status}")
    print()

    rows: List[Row] = []
    with tempfile.TemporaryDirectory(prefix="score-snap-live-") as tmp:
        data = Path(tmp)
        volume = data / "score_snapshots.json"
        seed_path = data / "seed.json"
        cycle_path = data / "cycle.json"
        os.environ["SCORE_SNAPSHOT_CYCLE_PATH"] = str(cycle_path)
        snaps.SCORE_SNAPSHOTS_PATH = str(volume)
        snaps.SCORE_SNAPSHOT_SEED_PATH = str(seed_path)
        shutil.copyfile(REPO_ROOT / "data_seeds" / "score_snapshots.json", seed_path)

        # SEED cold start
        polls, _ = _empty_polls_until_picks(lambda: snaps.build_top_picks_from_snapshot(None))
        rows.append(_row_from_served("SEED cold start", polls))

        # FRESH complete publish
        fresh = complete_snapshot_payload(
            day_rows=[{"netuid": 1, "total_score": 1.0}, {"netuid": 2, "total_score": 2.0}],
        )
        snaps.save_score_snapshot(fresh, str(volume))
        polls, _ = _empty_polls_until_picks(lambda: snaps.build_top_picks_from_snapshot(None))
        rows.append(_row_from_served("FRESH complete publish", polls))

        # kill -9 mid tmp write (volume removed so only seed can serve if publish aborts)
        if volume.exists():
            volume.unlink()
        _run_kill_mid_write(volume, seed_path)
        polls, _ = _empty_polls_until_picks(lambda: snaps.build_top_picks_from_snapshot(None))
        rows.append(_row_from_served("kill -9 mid tmp write", polls))

        # busy (top-picks path)
        import server

        server._TOP_PICKS_CACHE.update(at=0, payload=None)
        busy_out = server._snapshot_only_top_picks("busy")
        polls = 0 if busy_out.get("day_picks") else 1
        rows.append(_row_from_served("busy slot", polls))

        # timeout fallback
        timeout_out = server._snapshot_only_top_picks("timeout")
        polls = 0 if timeout_out.get("day_picks") else 1
        rows.append(_row_from_served("handler timeout", polls))

        # scorer error (incomplete volume; seed still serves)
        with open(volume, "w", encoding="utf-8") as handle:
            json.dump({"coverage": {"complete": False}, "day": []}, handle)
        polls, _ = _empty_polls_until_picks(lambda: snaps.build_top_picks_from_snapshot(None))
        rows.append(_row_from_served("scorer/coverage error", polls))

        # AGED >7200s (not blank)
        aged = complete_snapshot_payload(
            day_rows=[{"netuid": 3, "total_score": 3.0}],
            written_at="2018-01-01T00:00:00Z",
        )
        snaps.save_score_snapshot(aged, str(volume))
        served = snaps.read_served_snapshot(max_age_seconds=60)
        polls, _ = _empty_polls_until_picks(lambda: snaps.build_top_picks_from_snapshot(None))
        rows.append(
            Row(
                scenario="AGED >7200s",
                served_state=served.state.value,
                row_count=len(served.snapshot.get("day") or []) if served.snapshot else 0,
                scorer_revision=(served.snapshot or {}).get("scorer_revision"),
                scorer_digest=str((served.snapshot or {}).get("scorer_digest") or ""),
                empty_polls=polls,
            )
        )

    print("| Scenario | ServedState | day rows | scorer_revision | scorer_digest (prefix) | empty_polls |")
    print("|---|---|---:|---:|---|---:|")
    for row in rows:
        digest = row.scorer_digest[:12] + "…" if row.scorer_digest else ""
        print(
            f"| {row.scenario} | {row.served_state} | {row.row_count} | "
            f"{row.scorer_revision} | {digest} | {row.empty_polls} |"
        )
    print()
    print(f"expected_scorer_revision={SCORER_REVISION} digest_prefix={current_scorer_digest()[:12]}…")
    bad = [r for r in rows if r.served_state == "none" or (r.row_count == 0 and r.scenario != "scorer/coverage error")]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
