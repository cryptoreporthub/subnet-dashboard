"""Environment flags for the forward chain price recorder (#1395 Step 0)."""

from __future__ import annotations

import logging
import os

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

_DEFAULT_MIN_FREE_MB = 200
_DEFAULT_WARN_EXTRA_MB = 100


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        return int(raw)
    except ValueError:
        logger.warning("invalid %s=%r; using default %s", name, raw, default)
        return default


CHAIN_PRICE_MIN_FREE_MB = _int_env("CHAIN_PRICE_MIN_FREE_MB", _DEFAULT_MIN_FREE_MB)


def chain_price_warn_extra_mb() -> int:
    return _int_env("CHAIN_PRICE_WARN_EXTRA_MB", _DEFAULT_WARN_EXTRA_MB)


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
