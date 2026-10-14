"""Environment flags for the forward chain price recorder (#1395)."""

from __future__ import annotations

import logging
import os

from internal.chain_client import ChainClient

logger = logging.getLogger(__name__)

CHAIN_PRICE_DB_PATH = os.environ.get("CHAIN_PRICE_DB_PATH", "data/chain_prices.db")
SCHEMA_VERSION = 2
TICK_INTERVAL_SECONDS = 300
TICK_ANCHOR_OFFSET_SECONDS = 30
SPOT_DIVERGENCE_MAX = 0.005
SCHEMA_MISS_NULL_RATIO = 0.10
MAX_CONSECUTIVE_SCHEMA_MISS = 6
RETENTION_FULL_DAYS = 7
RETENTION_DAYS = 45
ROW_CAP = 600_000

_DEFAULT_MIN_FREE_MB = 200
_DEFAULT_WARN_EXTRA_MB = 100


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        return int(raw)
    except ValueError:
        logger.warning("invalid %s=%r; using default %s", name, raw, default)
        return default


def _non_negative_int_env(name: str, default: int) -> int:
    value = _int_env(name, default)
    if value < 0:
        logger.warning("negative %s=%s; using default %s", name, value, default)
        return default
    return value


CHAIN_PRICE_MIN_FREE_MB = _non_negative_int_env("CHAIN_PRICE_MIN_FREE_MB", _DEFAULT_MIN_FREE_MB)

# Back-compat alias for tests referencing MAX_CONSECUTIVE_HARD_FAILURES
MAX_CONSECUTIVE_HARD_FAILURES = MAX_CONSECUTIVE_SCHEMA_MISS


def chain_price_warn_extra_mb() -> int:
    return _non_negative_int_env("CHAIN_PRICE_WARN_EXTRA_MB", _DEFAULT_WARN_EXTRA_MB)


def forward_record_enabled() -> bool:
    return os.environ.get("CHAIN_PRICE_FORWARD_RECORD", "off").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def primary_rpc_endpoint() -> tuple[str, str]:
    """Return (url, provider_label) for the preferred endpoint."""
    providers = rpc_provider_endpoints()
    return providers[0]


def rpc_provider_endpoints() -> list[tuple[str, str]]:
    """Finney first when configured, then Blockmachine."""
    out: list[tuple[str, str]] = []
    finney = os.environ.get("FINNEY_RPC_URL", "").strip()
    if finney:
        out.append((finney.rstrip("/"), "finney"))
    blockmachine = os.environ.get("BLOCKMACHINE_RPC_URL", "https://rpc.blockmachine.io").rstrip(
        "/"
    )
    # Skip a duplicate so one failing endpoint is not retried as a "fallback" to itself.
    if not any(url == blockmachine for url, _ in out):
        out.append((blockmachine, "blockmachine"))
    return out


def rpc_provider_clients() -> list[tuple[str, ChainClient]]:
    return [
        (label, ChainClient(endpoint=url, init_volume_db=False))
        for url, label in rpc_provider_endpoints()
    ]
