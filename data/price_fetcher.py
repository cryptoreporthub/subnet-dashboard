"""
CoinGecko price fetcher with lightweight caching and rate-limit handling.

Used by the indicator layer to pull OHLC-style price series.
"""

import os
import time
from typing import Any, Dict, Optional

import pandas as pd
import requests

# Ensure the data directory exists at module load time.
os.makedirs('data', exist_ok=True)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
DEFAULT_CACHE_SECONDS = int(os.environ.get("PRICE_CACHE_SECONDS", "60"))
REQUEST_TIMEOUT = int(os.environ.get("PRICE_REQUEST_TIMEOUT", "20"))
USER_AGENT = "subnet-dashboard/indicator-layer"


class PriceFetcher:
    """Fetch and cache CoinGecko market-chart data as a pandas DataFrame."""

    def __init__(self, cache_seconds: int = DEFAULT_CACHE_SECONDS):
        self.cache_seconds = cache_seconds
        self._cache: Dict[str, Any] = {}
        self._last_fetch: Dict[str, float] = {}

    def _cache_key(self, coin_id: str, days: int, vs_currency: str) -> str:
        return f"{coin_id}:{vs_currency}:{days}"

    def _is_cached(self, key: str) -> bool:
        if key not in self._cache:
            return False
        age = time.time() - self._last_fetch.get(key, 0)
        return age < self.cache_seconds

    def _get(
        self, url: str, params: Optional[Dict] = None, retries: int = 2
    ) -> Optional[Dict]:
        attempt = 0
        last_exc = None
        while attempt <= retries:
            try:
                resp = requests.get(
                    url,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                    headers={"User-Agent": USER_AGENT},
                )
                if resp.status_code == 429:
                    time.sleep(min(2 ** attempt, 10))
                    attempt += 1
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_exc = e
                attempt += 1
                time.sleep(0.5 * attempt)
        return None

    def fetch_market_chart(
        self, coin_id: str, days: int = 30, vs_currency: str = "usd"
    ) -> pd.DataFrame:
        """Return a DataFrame with timestamp, datetime, and price columns."""
        key = self._cache_key(coin_id, days, vs_currency)
        if self._is_cached(key):
            return self._cache[key]

        url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart"
        params = {"vs_currency": vs_currency, "days": days, "interval": "daily"}
        data = self._get(url, params)
        if not data or "prices" not in data:
            raise RuntimeError(f"Failed to fetch market chart for {coin_id}")

        df = pd.DataFrame(data["prices"], columns=["timestamp", "price"])
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.drop_duplicates(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)

        self._cache[key] = df
        self._last_fetch[key] = time.time()
        return df

    def fetch_current_price(
        self, coin_id: str, vs_currency: str = "usd"
    ) -> Optional[float]:
        """Return the latest simple price, or None on failure."""
        url = f"{COINGECKO_BASE}/simple/price"
        params = {"ids": coin_id, "vs_currencies": vs_currency}
        data = self._get(url, params)
        if data and coin_id in data:
            return float(data[coin_id].get(vs_currency))
        return None
