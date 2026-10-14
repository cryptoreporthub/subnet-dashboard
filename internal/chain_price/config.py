"""Environment flags for the forward chain price recorder (#1395 Step 0)."""

from __future__ import annotations

import logging
import os
import shutil

logger = logging.getLogger(__name__)

CHAIN_PRICE_DB_PATH = os.environ.get("CHAIN_PRICE_DB_PATH", "data/chain_prices.db")
SCHEMA_VERSION = 1
TICK_INTERVAL_SECONDS = 300
TICK_ANCHOR_OFFSET_SECONDS = 30
SPOT_DIVERGENCE_MAX = 0.005
SCHEMA_MISS_NULL_RATIO = 0.10
MAX_CONSECUTIVE_HARD_FAILURES = 6
RETENTION_DAYS = 45
# Full 5m ticks for RETENTION_DAYS at ~128 subnets today; 256 slots = headroom without downsampling v1.
ROW_CAP = RETENTION_DAYS * (86400 // TICK_INTERVAL_SECONDS) * 256
MIN_REQUIRED_HEADROOM_BYTES = 300 * 1024 * 1024


def _forward_record_env_on() -> bool:
    return os.environ.get("CHAIN_PRICE_FORWARD_RECORD", "off").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def forward_record_enabled() -> bool:
    if not _forward_record_env_on():
        return False
    data_dir = os.environ.get("DATA_DIR", "data")
    try:
        free_bytes = shutil.disk_usage(data_dir).free
        if free_bytes < MIN_REQUIRED_HEADROOM_BYTES:
            logger.error(
                "CHAIN_PRICE_FORWARD_RECORD disabled: insufficient volume headroom "
                "(%d MB free, need %d MB)",
                free_bytes // (1024 * 1024),
                MIN_REQUIRED_HEADROOM_BYTES // (1024 * 1024),
            )
            return False
    except Exception as exc:
        logger.warning("disk headroom check failed: %s", exc)
    return True


def primary_rpc_endpoint() -> tuple[str, str]:
    """Return (url, provider_label)."""
    finney = os.environ.get("FINNEY_RPC_URL", "").strip()
    if finney:
        return finney.rstrip("/"), "finney"
    blockmachine = os.environ.get("BLOCKMACHINE_RPC_URL", "https://rpc.blockmachine.io").rstrip(
        "/"
    )
    return blockmachine, "blockmachine"
