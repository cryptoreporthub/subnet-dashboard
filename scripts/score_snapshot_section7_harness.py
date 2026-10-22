#!/usr/bin/env python3
"""Design §7 lifecycle harness — real entrypoint env, 3s /api/top-picks polls."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]


@dataclass
class PhaseResult:
    phase: str
    polls: int
    empty: int
    unreachable: int
    sample_state: str


def _poll_top_picks(base: str, timeout: float = 2.0) -> Dict[str, Any]:
    url = f"{base.rstrip('/')}/api/top-picks"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {}


def _empty_pick(body: Dict[str, Any]) -> bool:
    return not (body.get("day_picks") or body.get("hour_picks"))


def _run_phase(
    label: str,
    base: str,
    seconds: float,
    interval: float = 3.0,
) -> PhaseResult:
    polls = empty = unreachable = 0
    last_state = ""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        polls += 1
        body = _poll_top_picks(base)
        if not body:
            unreachable += 1
        elif _empty_pick(body):
            empty += 1
        meta = body.get("meta") or {}
        last_state = str(meta.get("snapshot_state") or meta.get("fallback_status") or "")
        time.sleep(interval)
    return PhaseResult(label, polls, empty, unreachable, last_state)


def _fly_env() -> Dict[str, str]:
    """Minimal env keys from fly.toml [env] for local harness."""
    return {
        "DISABLE_BACKGROUND_SCANS": "1",
        "PICK_HANDLER_TIMEOUT_SECONDS": os.environ.get("PICK_HANDLER_TIMEOUT_SECONDS", "8"),
        "SCORE_SNAPSHOT_SCHEDULER_ENABLED": "on",
        "SCORE_SNAPSHOT_REGISTRY_ONLY": "on",
        "PORT": os.environ.get("PORT", "18080"),
    }


def main() -> int:
    port = os.environ.get("PORT", "18080")
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, **_fly_env()}
    data_dir = REPO / "data"
    env["SCORE_SNAPSHOTS_PATH"] = str(data_dir / "score_snapshots.json")
    env["SCORE_SNAPSHOT_SEED_PATH"] = str(REPO / "data_seeds" / "score_snapshots.json")
    env["SCORE_SNAPSHOT_CYCLE_PATH"] = str(data_dir / "score_snapshot_cycle.json")

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", port],
        cwd=str(REPO),
        env=env,
    )
    results: List[PhaseResult] = []
    try:
        time.sleep(3)
        results.append(_run_phase("F", base, seconds=24))
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=5)
        time.sleep(2)
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", port],
            cwd=str(REPO),
            env=env,
        )
        time.sleep(3)
        results.append(_run_phase("R", base, seconds=15))
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=10)

    print("| Phase | polls | empty | unreachable | last_state |")
    print("|---|---:|---:|---:|---|")
    for row in results:
        print(f"| {row.phase} | {row.polls} | {row.empty} | {row.unreachable} | {row.sample_state} |")
    bad = [r for r in results if r.phase == "F" and r.empty > 0]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
