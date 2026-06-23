"""Price oracle – lightweight read-only facade over the persisted price cache.

Exposes ``get_token_price`` and ``get_all_prices`` for the Flask API layer
(``server.py`` routes ``/api/price-oracle/`` and ``/api/price-oracle``).

The cache file is written by ``internal.indicators.price_fetcher`` and stored at
``data/price_cache.json``.
"""

import os
from typing import Any, Dict, Optional, Union

from internal.file_utils import safe_read_json

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICE_CACHE_PATH = os.environ.get(
    "PRICE_CACHE_PATH", os.path.join(_PROJECT_ROOT, "data", "price_cache.json")
)


def _extract_price(entry: Dict[str, Any]) -> Optional[float]:
    """Extract the most recent close price from a cache entry."""
    candles = entry.get("candles") or []
    if candles:
        last = candles[-1]
        return float(last.get("close", last.get("price", 0)))
    return None


def get_token_price(token_id: Union[str, int] = "TAO") -> Optional[float]:
    """Return the latest price for *token_id* (subnet ID or ticker)."""
    cache = safe_read_json(PRICE_CACHE_PATH)
    # Normalise – the cache is keyed by numeric subnet id (str).
    key = str(token_id)
    entry = cache.get(key)
    if entry:
        price = _extract_price(entry)
        if price is not None:
            return price
    # Fallback: scan entries for matching ticker symbol.
    for _k, v in cache.items():
        if isinstance(v, dict) and v.get("ticker", "").upper() == key.upper():
            price = _extract_price(v)
            if price is not None:
                return price
    return None


def get_all_prices() -> Dict[str, Optional[float]]:
    """Return a mapping of every cached token id to its latest price."""
    cache = safe_read_json(PRICE_CACHE_PATH)
    return {k: _extract_price(v) for k, v in cache.items()}