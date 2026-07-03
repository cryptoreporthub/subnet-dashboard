"""Lightweight HTTPS JSON-RPC client for Bittensor-compatible nodes.

Designed for Blockmachine's free public RPC (https://rpc.blockmachine.io)
but works with any Substrate/Bittensor JSON-RPC endpoint that exposes the
Bittensor `swap_currentAlphaPrice` runtime call.
"""

import logging
import os
import time
from typing import Any, List, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_RPC_URL = os.environ.get("BLOCKMACHINE_RPC_URL", "https://rpc.blockmachine.io")
DEFAULT_TIMEOUT = int(os.environ.get("BLOCKMACHINE_RPC_TIMEOUT_SECONDS", "10"))
DEFAULT_RETRIES = int(os.environ.get("BLOCKMACHINE_RPC_RETRIES", "3"))
DEFAULT_BACKOFF = [1.0, 2.0, 4.0]
HEALTH_TTL_SECONDS = 30.0
PRICE_SCALE = float(os.environ.get("BITTENSOR_PRICE_SCALE", "1e9"))


class ChainClient:
    """HTTPS-only JSON-RPC client for Bittensor subnet state."""

    def __init__(
        self,
        endpoint: str = DEFAULT_RPC_URL,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        backoff: Optional[List[float]] = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff or DEFAULT_BACKOFF
        self._last_health_check: float = 0.0
        self._healthy: bool = True

    def _call(self, method: str, params: Optional[List[Any]] = None) -> Any:
        """Make a JSON-RPC call with retries and exponential backoff."""
        params = params or []
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": int(time.time() * 1000) % 2147483647,
        }
        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                response = requests.post(
                    self.endpoint,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                if "error" in data:
                    raise RuntimeError(data["error"])
                return data.get("result")
            except Exception as exc:
                last_error = exc
                sleep_for = self.backoff[min(attempt, len(self.backoff) - 1)]
                logger.debug("RPC %s attempt %d failed: %s", method, attempt, exc)
                if attempt < self.retries:
                    time.sleep(sleep_for)
        raise last_error or RuntimeError(f"RPC call to {method} failed")

    def is_healthy(self) -> bool:
        """Check node health via chain_getBlockHash; cache result for 30s."""
        now = time.time()
        if now - self._last_health_check < HEALTH_TTL_SECONDS:
            return self._healthy
        try:
            result = self._call("chain_getBlockHash", [0])
            self._healthy = bool(result)
        except Exception as exc:
            logger.debug("RPC health check failed: %s", exc)
            self._healthy = False
        self._last_health_check = now
        return self._healthy

    @property
    def degraded(self) -> bool:
        """True if the last health check reported an unhealthy node."""
        return not self._healthy

    def get_alpha_price(self, netuid: int) -> Optional[float]:
        """Return the current subnet alpha price in TAO, or None on failure."""
        try:
            result = self._call("swap_currentAlphaPrice", [netuid])
            if result is not None:
                return float(result) / PRICE_SCALE
        except Exception as exc:
            logger.debug("swap_currentAlphaPrice failed for netuid %s: %s", netuid, exc)
        return None
