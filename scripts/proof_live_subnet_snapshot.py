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


def _parity_at_pinned_block(finney_url: str, block_hash: str, netuid: int) -> dict[str, Any]:
    from internal.chain_client import PRICE_SCALE, ChainClient, _row_from_subnet_reserves
    from internal.chain_price.storage_keys import map_key_hex

    client = ChainClient(finney_url, init_volume_db=False, retries=1)
    keys = [
        map_key_hex(b"SubnetTAO", netuid),
        map_key_hex(b"SubnetAlphaIn", netuid),
    ]
    batch = client.query_storage_at(keys, block_hash)
    entry = batch[0] if batch else {}
    by_key = {row[0]: row[1] for row in entry.get("changes") or [] if row and len(row) >= 2}
    tao_raw = int.from_bytes(bytes.fromhex(by_key[keys[0]][2:]), "little")
    alpha_raw = int.from_bytes(bytes.fromhex(by_key[keys[1]][2:]), "little")
    row = _row_from_subnet_reserves(netuid, tao_raw, alpha_raw, "finney")
    swap_scaled = client._call_typed("swap_currentAlphaPrice", [netuid, block_hash])
    swap_price = int(swap_scaled) / PRICE_SCALE
    rel = abs(swap_price - row["price"]) / swap_price if swap_price else 0.0
    return {
        "block_hash": block_hash,
        "netuid": netuid,
        "rel_err": rel,
        "row_price": row["price"],
        "swap_price": swap_price,
    }


def main() -> int:
    finney = os.environ.get("FINNEY_RPC_URL", "https://entrypoint-finney.opentensor.ai").strip()
    bm = os.environ.get("BLOCKMACHINE_RPC_URL", "https://rpc.blockmachine.io").strip()
    if os.environ.get("PARITY_ONLY", "").strip() == "1":
        from internal.chain_price.live_subnet_snapshot import fetch_live_subnet_snapshot

        netuid = int(os.environ.get("PARITY_NETUID", "80"))
        snap = fetch_live_subnet_snapshot(time.monotonic() + 85.0)
        block_hash = os.environ.get("PARITY_BLOCK_HASH", "").strip() or snap.block_hash
        p = _parity_at_pinned_block(finney, block_hash, netuid)
        print(
            f"parity: block={p['block_hash'][:18]}… SN{p['netuid']} "
            f"rel={p['rel_err']:.2e} row={p['row_price']} swap={p['swap_price']}"
        )
        return 0
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
