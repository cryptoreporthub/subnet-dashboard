"""Build the image seed for a chain read via write_full_universe_snapshot."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from datetime import datetime, timezone
from typing import Any, Dict
from unittest import mock

from internal.council import score_snapshots as snaps
from internal.chain_read import ChainRead
from internal.council.seed_market_inputs import build_authoritative_hydrate_rows
from internal.subnet_universe import UniverseSnapshot, _validity_entry


def _membership_from_authoritative_rows(
    hydrate_rows: list[Dict[str, Any]],
    chain: ChainRead,
) -> UniverseSnapshot:
    resolved = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    netuids = tuple(int(r["netuid"]) for r in hydrate_rows)
    validity = {
        str(r["netuid"]): _validity_entry(validity="positive", sources=[str(r.get("source") or "price_cache")])
        for r in hydrate_rows
    }
    return UniverseSnapshot(
        netuids=netuids,
        rows=tuple(hydrate_rows),
        status="ok",
        resolved_at=resolved,
        degraded=False,
        cap_reached=False,
        refresh_incomplete=False,
        validity_map=validity,
        chain=chain,
    )


def build_image_seed_snapshot(
    *,
    chain: ChainRead,
    volume_path: str,
    cycle_path: str,
) -> Dict[str, Any]:
    """Score the chain's subnets with the real scorer and receipt code; returns write result."""
    hydrate, market_provenance = build_authoritative_hydrate_rows(chain.netuids)
    membership = _membership_from_authoritative_rows(hydrate, chain)

    import internal.subnet_universe as su
    import server

    with ExitStack() as patched:
        patched.enter_context(
            mock.patch.dict(
                os.environ,
                {"SCORE_SNAPSHOT_CYCLE_PATH": cycle_path, "SCORE_SNAPSHOT_REGISTRY_ONLY": "on"},
            )
        )
        patched.enter_context(mock.patch.object(snaps, "SCORE_SNAPSHOTS_PATH", volume_path))
        patched.enter_context(mock.patch.object(snaps, "SCORE_SNAPSHOT_SEED_PATH", volume_path + ".unused-seed"))
        patched.enter_context(mock.patch.object(su, "get_snapshot", lambda: membership))
        patched.enter_context(
            mock.patch.object(server, "_get_subnets_hydrate", lambda: (list(membership.rows), "registry-fallback"))
        )
        patched.enter_context(mock.patch.object(snaps, "_score_hour_enabled", lambda: False))
        out = snaps.write_full_universe_snapshot()
        if out.get("published") and os.path.isfile(volume_path):
            with open(volume_path, "r", encoding="utf-8") as handle:
                snap = json.load(handle)
            prov = snap.get("build_provenance")
            if isinstance(prov, dict):
                prov = dict(prov)
                prov["market_inputs"] = market_provenance
                snap["build_provenance"] = prov
                snaps.publish_complete_snapshot(snap, volume_path)
        return out
