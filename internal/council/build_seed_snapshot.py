"""Build a real 128/128 image seed via write_full_universe_snapshot."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

from internal.council import score_snapshots as snaps
from internal.council import snapshot_coverage as cov
from internal.council.seed_market_inputs import (
    IMAGE_SEED_NETUIDS,
    build_authoritative_hydrate_rows,
)
from internal.subnet_universe import UniverseSnapshot, _validity_entry


def _membership_from_authoritative_rows(
    hydrate_rows: list[Dict[str, Any]],
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
    )


def build_image_seed_snapshot(
    *,
    volume_path: str,
    cycle_path: str,
) -> Dict[str, Any]:
    """Score 128 subnets with real scorer functions; returns write result."""
    hydrate, market_provenance = build_authoritative_hydrate_rows(IMAGE_SEED_NETUIDS)
    os.environ["SCORE_SNAPSHOT_CYCLE_PATH"] = cycle_path
    os.environ["SCORE_SNAPSHOT_REGISTRY_ONLY"] = "on"
    snaps.SCORE_SNAPSHOTS_PATH = volume_path
    snaps.SCORE_SNAPSHOT_SEED_PATH = volume_path + ".unused-seed"
    membership = _membership_from_authoritative_rows(hydrate)

    import internal.subnet_universe as su
    import server

    prev_get = su.get_snapshot
    prev_hydrate = server._get_subnets_hydrate
    prev_receipt = cov.load_membership_receipt
    prev_hour = snaps._score_hour_enabled

    su.get_snapshot = lambda: membership  # type: ignore[method-assign]
    server._get_subnets_hydrate = lambda: (list(membership.rows), "registry-fallback")  # type: ignore[method-assign]
    cov.load_membership_receipt = lambda: {  # type: ignore[method-assign]
        "expected_netuids": list(IMAGE_SEED_NETUIDS),
        "fresh": True,
        "degraded": False,
        "cap_reached": False,
        "refresh_incomplete": False,
    }
    snaps._score_hour_enabled = lambda: False  # type: ignore[method-assign]
    try:
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
    finally:
        su.get_snapshot = prev_get  # type: ignore[method-assign]
        server._get_subnets_hydrate = prev_hydrate  # type: ignore[method-assign]
        cov.load_membership_receipt = prev_receipt  # type: ignore[method-assign]
        snaps._score_hour_enabled = prev_hour  # type: ignore[method-assign]
