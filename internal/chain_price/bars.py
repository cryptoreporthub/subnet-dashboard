"""Chain-sampled bar selection (not wired to grading) (#1395 Step 2)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from internal.chain_price import config as cfg
from internal.chain_price import db as price_db


def series_key(netuid: int, registered_at: int, schema_version: int = cfg.SCHEMA_VERSION) -> str:
    return f"chain:v{schema_version}:{netuid}:{registered_at}"


def max_staleness_seconds(horizon_s: int) -> int:
    return min(900, max(300, horizon_s // 8))


def get_chain_bar(
    netuid: int,
    registered_at: int,
    resolve_at_ms: int,
    *,
    horizon_s: int = 3600,
    path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Nearest ``chain_sampled`` bar at/before resolve time within staleness window."""
    stale_ms = max_staleness_seconds(horizon_s) * 1000
    sk = series_key(netuid, registered_at)
    row = price_db.select_chain_bar(
        netuid=netuid,
        registered_at=registered_at,
        series_key=sk,
        resolve_at_ms=resolve_at_ms,
        max_staleness_ms=stale_ms,
        path=path,
    )
    if not row:
        return None
    lag_s = max(0, (resolve_at_ms - int(row["ts_ms"])) // 1000)
    return {
        "price_source": "chain_sampled",
        "price_provider": row["provider"],
        "price_block": row["block"],
        "price_block_hash": row.get("block_hash"),
        "price_lag_seconds": lag_s,
        "price_unit": row.get("unit", "tao"),
        "quality": row["quality"],
        "schema_version": row["schema_version"],
        "series_key": sk,
        "price_tao": row["price_tao"],
        "registered_at": row["registered_at"],
    }
