"""Environment flags for the forward chain price recorder (#1395 Step 0)."""

from __future__ import annotations

import os

CHAIN_PRICE_DB_PATH = os.environ.get("CHAIN_PRICE_DB_PATH", "data/chain_prices.db")
SCHEMA_VERSION = 1
TICK_INTERVAL_SECONDS = 300
TICK_ANCHOR_OFFSET_SECONDS = 30
SPOT_DIVERGENCE_MAX = 0.005
SCHEMA_MISS_NULL_RATIO = 0.10
MAX_CONSECUTIVE_HARD_FAILURES = 6
RETENTION_DAYS = 45
ROW_CAP = 600_000


def forward_record_enabled() -> bool:
    return os.environ.get("CHAIN_PRICE_FORWARD_RECORD", "off").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def primary_rpc_endpoint() -> tuple[str, str]:
    """Return (url, provider_label)."""
    finney = os.environ.get("FINNEY_RPC_URL", "").strip()
    if finney:
        return finney.rstrip("/"), "finney"
    blockmachine = os.environ.get("BLOCKMACHINE_RPC_URL", "https://rpc.blockmachine.io").rstrip(
        "/"
    )
    return blockmachine, "blockmachine"
