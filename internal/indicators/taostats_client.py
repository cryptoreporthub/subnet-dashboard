"""TaoStats API client for on-chain Bittensor data."""
import os
import time
import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

TAOSTATS_API_KEY = os.environ.get("TAOSTATS_API_KEY", "")
TAOSTATS_BASE_URL = "https://api.taostats.io/api/v1"


def _headers():
    return {"Authorization": f"Bearer {TAOSTATS_API_KEY}", "Accept": "application/json"}


def _get(endpoint, params=None):
    if not TAOSTATS_API_KEY:
        logger.warning("TAOSTATS_API_KEY not set, skipping TaoStats fetch")
        return None
    url = f"{TAOSTATS_BASE_URL}{endpoint}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url += f"?{qs}"
    try:
        req = urllib.request.Request(url, headers=_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.error(f"TaoStats API error: {e}")
        return None


def get_dtao_pool_latest(netuid: int):
    """Get dTAO pool data for a subnet — price, liquidity, conviction, delegation."""
    return _get(f"/dtao/pool/latest/v1", {"netuid": netuid})


def get_subnet_delegation_flow(netuid: int):
    """Get delegation flow data — how much TAO is entering/exiting the subnet."""
    return _get(f"/subnets/{netuid}/delegations", {"limit": 10})


def get_subnet_registration_cost(netuid: int):
    """Get current registration cost for a subnet."""
    return _get(f"/subnets/{netuid}/registration")


def get_tao_price():
    """Get current TAO price."""
    return _get("/tao/price")


def get_tao_price_history():
    """Get TAO price history for chart candles."""
    return _get("/tao/price/history", {"limit": 168})  # 7 days of hourly data