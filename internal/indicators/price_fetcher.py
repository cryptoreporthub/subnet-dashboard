"""Price fetcher for subnet token OHLCV candle data."""

import json
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests

PRICE_PAIRS_PATH = os.environ.get("PRICE_PAIRS_PATH", "config/price_pairs.json")
PRICE_CACHE_PATH = os.environ.get("PRICE_CACHE_PATH", "data/price_cache.json")
COINGECKO_API = "https://api.coingecko.com/api/v3"
DEFAULT_DAYS = int(os.environ.get("PRICE_LOOKBACK_DAYS", "7"))
CACHE_TTL_SECONDS = int(os.environ.get("PRICE_CACHE_TTL_SECONDS", "300"))
# Default to synthetic candles on serverless/Fly hosts to avoid long network
# stalls and CoinGecko rate limits on the very first tick.
USE_LIVE_PRICES = os.environ.get("INDICATOR_USE_LIVE_PRICES", "false").lower() == "true"
LIVE_PRICE_TIMEOUT = int(os.environ.get("LIVE_PRICE_TIMEOUT_SECONDS", "10"))

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _load_json(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_json(path: str, data: Dict[str, Any]) -> None:
    dir_name = os.path.dirname(path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_path, path)

def _load_price_pairs(path: str = PRICE_PAIRS_PATH) -> Dict[str, Any]:
    return _load_json(path)

def _coingecko_id_for_subnet(subnet_id: str, pairs: Dict[str, Any]) -> str:
    info = pairs.get(str(subnet_id)) or pairs.get(subnet_id)
    if info and info.get("coingecko_id") and info["coingecko_id"] != "unknown":
        return info["coingecko_id"]
    # Use a synthetic id so callers can fall back to generated candles.
    return f"subnet-{subnet_id}"

def _fetch_coingecko_ohlc(coin_id: str, days: int = DEFAULT_DAYS) -> List[Dict[str, Any]]:
    """Fetch daily OHLC from CoinGecko free API and convert to hourly-like candles."""
    url = f"{COINGECKO_API}/coins/{coin_id}/ohlc"
    params = {"vs_currency": "usd", "days": days}
    response = requests.get(url, params=params, timeout=LIVE_PRICE_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list) or len(data) < 2:
        raise RuntimeError(f"CoinGecko returned empty OHLC for {coin_id}")

    candles: List[Dict[str, Any]] = []
    for item in data:
        ts_ms, o, h, l, c = item
        candles.append(
            {
                "timestamp": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": 0.0,
            }
        )
    return candles

def _synthetic_candles(coin_id: str, days: int = DEFAULT_DAYS) -> List[Dict[str, Any]]:
    """Generate deterministic synthetic OHLCV candles when no live source exists."""
    candles: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    seed = sum(ord(ch) for ch in coin_id)
    price = 1.0 + (seed % 100) / 10.0
    hours = days * 24
    for i in range(hours, 0, -1):
        ts = now - timedelta(hours=i)
        # Deterministic wobble based on index and seed.
        change = ((i * 7 + seed) % 11 - 5) / 100.0
        o = price
        c = price * (1 + change)
        h = max(o, c) * (1 + abs(change) * 0.3)
        l = min(o, c) * (1 - abs(change) * 0.3)
        v = float((i * 13 + seed) % 10000)
        candles.append(
            {
                "timestamp": ts.isoformat(),
                "open": round(o, 6),
                "high": round(h, 6),
                "low": round(l, 6),
                "close": round(c, 6),
                "volume": round(v, 2),
            }
        )
        price = c
    return candles

def fetch_ohlcv(
    subnet_id: str,
    days: int = DEFAULT_DAYS,
    use_cache: bool = True,
    cache_path: str = PRICE_CACHE_PATH,
) -> List[Dict[str, Any]]:
    """
    Fetch OHLCV candles for a subnet token.

    Tries CoinGecko first when INDICATOR_USE_LIVE_PRICES=true, then falls back
    to synthetic candles. By default synthetic candles are used on production
    servers to avoid network stalls and rate limits during deploy.
    """
    pairs = _load_price_pairs()
    coin_id = _coingecko_id_for_subnet(subnet_id, pairs)
    cache_key = str(subnet_id)

    cache = _load_json(cache_path) if use_cache else {}
    now = time.time()
    cached = cache.get(cache_key)
    if cached and (now - cached.get("cached_at", 0)) < CACHE_TTL_SECONDS:
        return cached.get("candles", [])

    candles: List[Dict[str, Any]] = []
    source = "unknown"
    error = None

    should_try_live = (
        USE_LIVE_PRICES
        and not coin_id.startswith("subnet-")
        and coin_id != "unknown"
    )

    try:
        if should_try_live:
            candles = _fetch_coingecko_ohlc(coin_id, days=days)
            source = "coingecko"
        else:
            raise RuntimeError(f"Live prices disabled or unavailable for subnet {subnet_id}")
    except Exception as exc:
        error = str(exc)
        candles = _synthetic_candles(coin_id, days=days)
        source = "synthetic"

    if use_cache:
        cache[cache_key] = {
            "coin_id": coin_id,
            "source": source,
            "cached_at": now,
            "fetched_at": _now_iso(),
            "error": error,
            "candles": candles,
        }
        _save_json(cache_path, cache)

    return candles
