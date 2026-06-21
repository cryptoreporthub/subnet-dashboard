"""
Price Oracle — fetches crypto prices from CoinGecko free tier.

Handles rate limiting, caches results, and provides a fallback to
cached data when the API is unavailable.
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
CACHE_PATH = os.environ.get("PRICE_ORACLE_CACHE_PATH", "data/price_oracle_cache.json")
CACHE_TTL_SECONDS = int(os.environ.get("PRICE_ORACLE_CACHE_TTL", "300"))
REQUEST_TIMEOUT = int(os.environ.get("PRICE_ORACLE_TIMEOUT", "15"))
USER_AGENT = "subnet-dashboard/price-oracle"

# CoinGecko IDs for tokens we track.
# Maps subnet token symbols to CoinGecko coin IDs.
TOKEN_ID_MAP: Dict[str, str] = {
    "TAO": "bittensor",
    "FET": "fetch-ai",
    "RENDER": "render-token",
    "HYPE": "hyperliquid",
    "VVV": "valinity",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_cache() -> Dict[str, Any]:
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    dir_name = os.path.dirname(CACHE_PATH)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
    temp = CACHE_PATH + ".tmp"
    with open(temp, "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(temp, CACHE_PATH)


def _cache_key(coin_id: str, vs_currency: str) -> str:
    return f"{coin_id}:{vs_currency}"


def _is_fresh(cached_entry: Dict[str, Any]) -> bool:
    age = time.time() - cached_entry.get("fetched_at", 0)
    return age < CACHE_TTL_SECONDS


def _api_get(url: str, params: Optional[Dict] = None, retries: int = 2) -> Optional[Dict]:
    attempt = 0
    while attempt <= retries:
        try:
            resp = requests.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
            if resp.status_code == 429:
                wait = min(2 ** attempt, 10)
                time.sleep(wait)
                attempt += 1
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception:
            attempt += 1
            time.sleep(0.5 * attempt)
    return None


def fetch_current_price(
    token: str,
    vs_currency: str = "usd",
    force_refresh: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Fetch the current price for a token.

    Returns:
        {
            "token": "TAO",
            "coin_id": "bittensor",
            "price_usd": 123.45,
            "fetched_at": "2026-06-21T...",
            "source": "api" | "cache" | "fallback",
        }
        or None if all sources fail.
    """
    coin_id = TOKEN_ID_MAP.get(token.upper())
    if not coin_id:
        return None

    cache = _load_cache()
    key = _cache_key(coin_id, vs_currency)

    # Return fresh cache if available and not forcing refresh.
    if not force_refresh:
        cached = cache.get(key)
        if cached and _is_fresh(cached):
            cached["source"] = "cache"
            return cached

    # Try live API.
    url = f"{COINGECKO_BASE}/simple/price"
    params = {"ids": coin_id, "vs_currencies": vs_currency}
    data = _api_get(url, params)

    if data and coin_id in data:
        price = float(data[coin_id].get(vs_currency, 0))
        entry = {
            "token": token.upper(),
            "coin_id": coin_id,
            "price_usd": price,
            "fetched_at": time.time(),
            "fetched_iso": _now_iso(),
            "source": "api",
        }
        cache[key] = entry
        _save_cache(cache)
        return entry

    # Fallback: return stale cache if available.
    stale = cache.get(key)
    if stale:
        stale["source"] = "fallback"
        return stale

    return None


def fetch_prices(
    tokens: Optional[list] = None,
    vs_currency: str = "usd",
) -> Dict[str, Any]:
    """
    Fetch prices for multiple tokens at once.

    Returns:
        {
            "prices": {"TAO": {...}, "FET": {...}, ...},
            "fetched_at": "...",
            "errors": [...],
        }
    """
    if tokens is None:
        tokens = list(TOKEN_ID_MAP.keys())

    coin_ids = []
    token_by_coin = {}
    for t in tokens:
        cid = TOKEN_ID_MAP.get(t.upper())
        if cid:
            coin_ids.append(cid)
            token_by_coin[cid] = t.upper()

    if not coin_ids:
        return {"prices": {}, "fetched_at": _now_iso(), "errors": ["no valid tokens"]}

    cache = _load_cache()
    results: Dict[str, Any] = {}
    errors: list = []
    needs_fetch: list = []

    # Check cache first.
    for cid in coin_ids:
        key = _cache_key(cid, vs_currency)
        cached = cache.get(key)
        if cached and _is_fresh(cached):
            cached["source"] = "cache"
            results[token_by_coin[cid]] = cached
        else:
            needs_fetch.append(cid)

    # Batch fetch from API.
    if needs_fetch:
        url = f"{COINGECKO_BASE}/simple/price"
        params = {"ids": ",".join(needs_fetch), "vs_currencies": vs_currency}
        data = _api_get(url, params)

        now_ts = time.time()
        now_iso = _now_iso()

        for cid in needs_fetch:
            token = token_by_coin[cid]
            if data and cid in data:
                price = float(data[cid].get(vs_currency, 0))
                entry = {
                    "token": token,
                    "coin_id": cid,
                    "price_usd": price,
                    "fetched_at": now_ts,
                    "fetched_iso": now_iso,
                    "source": "api",
                }
                cache[_cache_key(cid, vs_currency)] = entry
                results[token] = entry
            else:
                # Fallback to stale cache.
                stale = cache.get(_cache_key(cid, vs_currency))
                if stale:
                    stale["source"] = "fallback"
                    results[token] = stale
                else:
                    errors.append(f"no price data for {token}")

        _save_cache(cache)

    return {
        "prices": results,
        "fetched_at": _now_iso(),
        "errors": errors,
    }


def get_price_for_subnet_token(
    subnet_name: str,
    vs_currency: str = "usd",
) -> Optional[float]:
    """
    Try to find a price for a subnet by matching its name against known tokens.
    Returns the price in USD or None.
    """
    # Try direct token match.
    upper = subnet_name.upper() if subnet_name else ""
    for token, cid in TOKEN_ID_MAP.items():
        if token in upper or upper in token:
            result = fetch_current_price(token, vs_currency)
            if result:
                return result["price_usd"]
    return None