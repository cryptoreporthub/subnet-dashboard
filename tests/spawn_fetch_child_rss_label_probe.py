"""Subprocess: worker module import + spawn fetch child (mirrors inline worker path)."""

from __future__ import annotations

import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
os.chdir(_root)
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Prod: fetch spawn may import internal.worker before run_fetch_child sets child env.
import internal.worker  # noqa: E402,F401


def _spawn_fetch_child_logging_probe_child() -> None:
    import internal.worker  # noqa: F401 — spawn / __mp_main__ re-import

    os.environ["LIVE_SUBNETS_FETCH_CHILD"] = "1"
    from internal.app_logging import configure_app_logging

    configure_app_logging()
    time.sleep(0.15)


def _spawn_child_configures_logging_after_worker_import() -> None:
    ctx = mp.get_context("spawn")
    proc = ctx.Process(target=_spawn_fetch_child_logging_probe_child)
    proc.start()
    proc.join(timeout=30)
    if proc.exitcode != 0:
        raise SystemExit(proc.exitcode or 1)


def main() -> None:
    os.environ.pop("PYTEST_CURRENT_TEST", None)
    os.environ.pop("CI", None)
    os.environ.pop("GITHUB_ACTIONS", None)
    os.environ["RUN_MODE"] = "worker"
    os.environ["WORKER_HEAVY"] = "essential"
    os.environ["LIVE_SUBNETS_MP_CONTEXT"] = "spawn"
    os.environ["PROCESS_RSS_LOG_INTERVAL_SECONDS"] = "0.05"
    os.environ["LIVE_SUBNETS_TEST_ROWS_JSON"] = '[{"netuid": 1, "price": 1.0}]'
    os.environ["LIVE_SUBNETS_SPAWN_GRACE_SECONDS"] = "10"

    _spawn_child_configures_logging_after_worker_import()

    from internal import live_subnets

    out = live_subnets._fetch_chain_data()
    if not out:
        raise SystemExit(5)
    time.sleep(0.2)


if __name__ == "__main__":
    main()
