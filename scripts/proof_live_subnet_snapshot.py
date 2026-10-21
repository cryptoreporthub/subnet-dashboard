#!/usr/bin/env python3
"""Re-runnable live proof for batched live_subnet_snapshot (#1473).

Uses public Finney + Blockmachine endpoints (no secrets). Counts HTTP POSTs via
requests.post wrapper.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any, Callable

# Repo root on path when run as scripts/proof_live_subnet_snapshot.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

POST_COUNT = 0
_ORIG_POST: Callable[..., Any] | None = None


def _counting_post(*args, **kwargs):
    global POST_COUNT
    POST_COUNT += 1
    assert _ORIG_POST is not None
    return _ORIG_POST(*args, **kwargs)


def _run_case(label: str, *, finney_url: str | None, blockmachine_url: str) -> dict[str, Any]:
    import requests

    global POST_COUNT, _ORIG_POST
    if _ORIG_POST is None:
        _ORIG_POST = requests.post
    requests.post = _counting_post  # type: ignore[method-assign]
    POST_COUNT = 0

    if finney_url:
        os.environ["FINNEY_RPC_URL"] = finney_url
    else:
        os.environ.pop("FINNEY_RPC_URL", None)
    os.environ["BLOCKMACHINE_RPC_URL"] = blockmachine_url
    os.environ["BLOCKMACHINE_RPC_TIMEOUT_SECONDS"] = "4"
    os.environ["BLOCKMACHINE_RPC_RETRIES"] = "1"

    from internal.chain_price.live_subnet_snapshot import fetch_live_subnet_snapshot

    started = time.perf_counter()
    deadline = time.monotonic() + 85.0
    snap = fetch_live_subnet_snapshot(deadline)
    wall = time.perf_counter() - started
    members = len(snap.requested_netuids)
    return {
        "case": label,
        "members": members,
        "rows": len(snap.rows),
        "posts": POST_COUNT,
        "wall_s": round(wall, 2),
        "provider": snap.provider,
        "block_hash": snap.block_hash[:18] + "…" if snap.block_hash else "",
    }


def main() -> int:
    finney = os.environ.get("FINNEY_RPC_URL", "https://entrypoint-finney.opentensor.ai").strip()
    bm = os.environ.get("BLOCKMACHINE_RPC_URL", "https://rpc.blockmachine.io").strip()
    cases = [
        _run_case("finney_first", finney_url=finney, blockmachine_url=bm),
        _run_case("blockmachine_only", finney_url=None, blockmachine_url=bm),
    ]
    for row in cases:
        print(
            f"{row['case']}: members={row['members']} rows={row['rows']} "
            f"POSTs={row['posts']} wall={row['wall_s']}s provider={row['provider']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
