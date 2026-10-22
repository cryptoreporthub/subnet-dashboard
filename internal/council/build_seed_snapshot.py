"""Build a real 128/128 image seed via write_full_universe_snapshot."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict

from internal.council import score_snapshots as snaps
from internal.council import snapshot_coverage as cov
from internal.subnet_universe import UniverseSnapshot, _validity_entry


def _membership_128() -> UniverseSnapshot:
    resolved = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rows = [
        {
            "netuid": n,
            "name": f"Alpha Subnet {n}",
            "price": 1.0 + n * 0.01,
            "volume": 1000.0 + n,
            "source": "taomarketcap",
        }
        for n in range(1, 129)
    ]
    validity = {
        str(n): _validity_entry(validity="positive", sources=["taomarketcap"])
        for n in range(1, 129)
    }
    return UniverseSnapshot(
        netuids=tuple(range(1, 129)),
        rows=tuple(rows),
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
    os.environ["SCORE_SNAPSHOT_CYCLE_PATH"] = cycle_path
    os.environ["SCORE_SNAPSHOT_REGISTRY_ONLY"] = "on"
    snaps.SCORE_SNAPSHOTS_PATH = volume_path
    snaps.SCORE_SNAPSHOT_SEED_PATH = volume_path + ".unused-seed"
    membership = _membership_128()
    hydrate = list(membership.rows)

    import internal.subnet_universe as su
    import server

    prev_get = su.get_snapshot
    prev_hydrate = server._get_subnets_hydrate
    prev_receipt = cov.load_membership_receipt
    prev_hour = snaps._score_hour_enabled

    su.get_snapshot = lambda: membership  # type: ignore[method-assign]
    server._get_subnets_hydrate = lambda: (hydrate, "registry-fallback")  # type: ignore[method-assign]
    cov.load_membership_receipt = lambda: {  # type: ignore[method-assign]
        "expected_netuids": list(range(1, 129)),
        "fresh": True,
        "degraded": False,
        "cap_reached": False,
        "refresh_incomplete": False,
    }
    snaps._score_hour_enabled = lambda: False  # type: ignore[method-assign]
    try:
        return snaps.write_full_universe_snapshot()
    finally:
        su.get_snapshot = prev_get  # type: ignore[method-assign]
        server._get_subnets_hydrate = prev_hydrate  # type: ignore[method-assign]
        cov.load_membership_receipt = prev_receipt  # type: ignore[method-assign]
        snaps._score_hour_enabled = prev_hour  # type: ignore[method-assign]
