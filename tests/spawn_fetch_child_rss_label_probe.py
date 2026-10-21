"""Subprocess: spawn live_subnets fetch child and emit one RSS heartbeat line."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.environ.pop("PYTEST_CURRENT_TEST", None)
    os.environ.pop("CI", None)
    os.environ.pop("GITHUB_ACTIONS", None)
    os.environ["RUN_MODE"] = "worker"
    os.environ["WORKER_HEAVY"] = "essential"
    os.environ["LIVE_SUBNETS_MP_CONTEXT"] = "spawn"
    os.environ["PROCESS_RSS_LOG_INTERVAL_SECONDS"] = "0.05"
    os.environ["LIVE_SUBNETS_TEST_ROWS_JSON"] = '[{"netuid": 1, "price": 1.0}]'
    os.environ["LIVE_SUBNETS_SPAWN_GRACE_SECONDS"] = "10"

    from internal import live_subnets

    out = live_subnets._fetch_chain_data()
    if not out:
        raise SystemExit(1)
    time.sleep(0.25)


if __name__ == "__main__":
    main()
