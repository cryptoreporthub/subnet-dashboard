"""Subprocess helper: spawn live_subnets fetch with web entry script as parent context."""

from __future__ import annotations

import multiprocessing as mp
import os
import sys


def _child_fetch() -> None:
    import internal.snapshot_guard as guard

    if guard._ORIG is not None:
        raise SystemExit(2)
    os.environ.setdefault(
        "LIVE_SUBNETS_TEST_ROWS_JSON",
        '[{"netuid": 1, "price": 1.0}]',
    )
    from internal.live_subnets import _fetch_chain_data

    data = _fetch_chain_data()
    if not data or data[0].get("netuid") != 1:
        raise SystemExit(3)


def main() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(repo_root)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    os.environ["LIVE_SUBNETS_MP_CONTEXT"] = "spawn"
    ctx = mp.get_context("spawn")
    proc = ctx.Process(target=_child_fetch, name="spawn-fetch-test")
    proc.start()
    proc.join(timeout=30)
    if proc.exitcode != 0:
        raise SystemExit(proc.exitcode or 1)


if __name__ == "__main__":
    main()
