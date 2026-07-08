"""Price fetcher for subnet token OHLCV candle data.

Tiered strategy:
1. TaoMarketCap (TMC) primary:
   - /public/v1/subnets/ -> subnet latest_snapshot.price (alpha price in TAO)
   - /public/v1/market/candle-data/ -> hourly TAO/USD candles
   - Derive subnet USD candles by scaling TAO/USD OHLC by the subnet alpha price.
2. GeckoTerminal fallback for explicitly mapped DEX pools:
   - config/price_pairs.json may contain "geckoterminal": {"network": ..., "pool": ...}
   - /networks/{network}/pools/{pool}/ohlcv/hour
3. Synthetic final fallback (deterministic, always available).
"""

import json
import os
import tempfile
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests

try:
    from internal.chain_client import ChainClient
except Exception:
    ChainClient = None  # type: ignore

# Ensure the data directory exists at module load time.
os.makedirs('data', exist_ok=True)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRICE_PAIRS_PATH = os.environ.get(
    "PRICE_PAIRS_PATH", os.path.join(_PROJECT_ROOT, "config", "price_pairs.json")
)
PRICE_CACHE_PATH = os.environ.get(
    "PRICE_CACHE_PATH", os.path.join(_PROJECT_ROOT, "data", "price_cache.json")
)
TAO_MARKET_CAP_API = "https://api.taomarketcap.com"
GECKO_TERMINAL_API = "https://api.geckoterminal.com/api/v2"
DEFAULT_DAYS = int(os.environ.get("PRICE_LOOKBACK_DAYS", "7"))
CACHE_TTL_SECONDS = int(os.environ.get("PRICE_CACHE_TTL_SECONDS", "300"))
TMC_CACHE_TTL_SECONDS = int(os.environ.get("TMC_CACHE_TTL_SECONDS", "60"))
# Use live prices by default. TaoMarketCap is the primary source, GeckoTerminal
# is the fallback, and synthetic candles are the last resort.
USE_LIVE_PRICES = os.environ.get("INDICATOR_USE_LIVE_PRICES", "true").lower() == "true"
LIVE_PRICE_TIMEOUT = int(os.environ.get("LIVE_PRICE_TIMEOUT_SECONDS", "10"))
BLOCKMACHINE_RPC_URL = os.environ.get("BLOCKMACHINE_RPC_URL", "https://rpc.blockmachine.io")

# Deterministic anchor for synthetic candles so repeated calls produce identical
# output (required by the test suite and useful for reproducible local runs).
_SYNTHETIC_EPOCH = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

# Module-level caches for TaoMarketCap data so multiple subnet fetches share one
# subnets snapshot and one TAO/USD candle series within the TTL window.
_tmc_subnets_cache: Dict[str, Any] = {"data": None, "cached_at": 0.0}
_tmc_candles_cache: Dict[str, Any] = {"data": None, "cached_at": 0.0}

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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def _load_price_pairs(path: str = PRICE_PAIRS_PATH) -> Dict[str, Any]:
    return _load_json(path)

def _price_sources_for_subnet(subnet_id: str, pairs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return ordered list of price sources to attempt for a subnet."""
    info = pairs.get(str(subnet_id)) or pairs.get(subnet_id) or {}
    sources: List[Dict[str, Any]] = []

    # Primary: TaoMarketCap. Default netuid to the subnet id if not mapped.
    netuid = info.get("taomarketcap_netuid", subnet_id)
    sources.append({"source": "taomarketcap", "netuid": str(netuid)})

    # Fallback: GeckoTerminal for explicitly mapped DEX pools.
    gt = info.get("geckoterminal")
    if isinstance(gt, dict) and gt.get("network") and gt.get("pool"):
        sources.append(
            {
                "source": "geckoterminal",
                "network": str(gt["network"]),
                "pool": str(gt["pool"]),
            }
        )

    # Fallback: Blockmachine JSON-RPC alpha price + TAO/USD history.
    sources.append({"source": "blockmachine", "netuid": str(netuid)})

    # Final fallback: deterministic synthetic candles.
    sources.append({"source": "synthetic", "key": f"subnet-{subnet_id}"})
    return sources

def _fetch_tmc_subnets(timeout: int = LIVE_PRICE_TIMEOUT) -> Dict[str, Dict[str, Any]]:
    """Fetch and cache the TaoMarketCap subnets snapshot keyed by netuid."""
    now = time.time()
    cached = _tmc_subnets_cache["data"]
    if cached is not None and (now - _tmc_subnets_cache["cached_at"]) < TMC_CACHE_TTL_SECONDS:
        return cached

    url = f"{TAO_MARKET_CAP_API}/public/v1/subnets/"
    params = {"limit": 200}
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    results = data.get("results", []) if isinstance(data, dict) else data
    if not isinstance(results, list):
        raise RuntimeError("TaoMarketCap /subnets/ returned unexpected shape")

    mapping = {str(item["netuid"]): item for item in results if "netuid" in item}
    _tmc_subnets_cache["data"] = mapping
    _tmc_subnets_cache["cached_at"] = now
    return mapping

def _fetch_tmc_candles(timeout: int = LIVE_PRICE_TIMEOUT) -> List[Dict[str, Any]]:
    """Fetch and cache the global hourly TAO/USD candle series."""
    now = time.time()
    cached = _tmc_candles_cache["data"]
    if cached is not None and (now - _tmc_candles_cache["cached_at"]) < TMC_CACHE_TTL_SECONDS:
        return cached

    url = f"{TAO_MARKET_CAP_API}/public/v1/market/candle-data/"
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise RuntimeError("TaoMarketCap /market/candle-data/ returned unexpected shape")

    _tmc_candles_cache["data"] = data
    _tmc_candles_cache["cached_at"] = now
    return data

def _derive_subnet_candles(alpha_price: float, days: int, tao_candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Scale TAO/USD OHLCV by a subnet alpha price to derive subnet USD candles."""
    if alpha_price <= 0:
        raise RuntimeError("Invalid alpha price for subnet candle derivation")
    if len(tao_candles) < 2:
        raise RuntimeError("Insufficient TAO/USD candles for subnet derivation")

    needed = days * 24
    if len(tao_candles) > needed:
        tao_candles = tao_candles[-needed:]

    derived: List[Dict[str, Any]] = []
    for candle in tao_candles:
        derived.append(
            {
                "timestamp": candle["timestamp"],
                "open": round(float(candle["open"]) * alpha_price, 6),
                "high": round(float(candle["high"]) * alpha_price, 6),
                "low": round(float(candle["low"]) * alpha_price, 6),
                "close": round(float(candle["close"]) * alpha_price, 6),
                "volume": round(float(candle.get("volume", 0.0)), 6),
            }
        )
    return derived


_chain_client: Optional[Any] = None


def _get_chain_client() -> Optional[Any]:
    """Lazy singleton for the Blockmachine JSON-RPC client."""
    global _chain_client
    if _chain_client is None and ChainClient is not None:
        try:
            _chain_client = ChainClient(endpoint=BLOCKMACHINE_RPC_URL)
        except Exception:
            _chain_client = None
    return _chain_client


def _fetch_rpc_subnet_candles(netuid: str, days: int = DEFAULT_DAYS) -> List[Dict[str, Any]]:
    """Derive hourly USD candles from Blockmachine RPC alpha price + TAO/USD history."""
    client = _get_chain_client()
    if client is None:
        raise RuntimeError("Blockmachine RPC client is not available")
    if not client.is_healthy():
        raise RuntimeError("Blockmachine RPC client is unhealthy")

    alpha_price = client.get_alpha_price(int(netuid))
    if alpha_price is None or alpha_price <= 0:
        raise RuntimeError(f"Blockmachine RPC returned invalid alpha price for netuid {netuid}")

    tao_candles = _fetch_tmc_candles()
    return _derive_subnet_candles(alpha_price, days, tao_candles)


def _fetch_tmc_subnet_candles(netuid: str, days: int = DEFAULT_DAYS) -> List[Dict[str, Any]]:
    """Derive hourly USD candles for a subnet from TAO/USD * alpha price."""
    subnets = _fetch_tmc_subnets()
    snapshot = subnets.get(str(netuid))
    if not snapshot:
        raise RuntimeError(f"TaoMarketCap has no snapshot for netuid {netuid}")

    latest = snapshot.get("latest_snapshot", {})
    alpha_price = float(latest.get("price", 0.0))
    if alpha_price <= 0:
        raise RuntimeError(f"TaoMarketCap returned invalid alpha price for netuid {netuid}")

    tao_candles = _fetch_tmc_candles()
    return _derive_subnet_candles(alpha_price, days, tao_candles)

def _fetch_geckoterminal_ohlcv(
    network: str,
    pool: str,
    days: int = DEFAULT_DAYS,
    timeout: int = LIVE_PRICE_TIMEOUT,
) -> List[Dict[str, Any]]:
    """Fetch hourly OHLCV from a GeckoTerminal pool."""
    url = f"{GECKO_TERMINAL_API}/networks/{network}/pools/{pool}/ohlcv/hour"
    params = {"limit": days * 24}
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    ohlcv_list = (
        data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
        if isinstance(data, dict)
        else []
    )
    if len(ohlcv_list) < 2:
        raise RuntimeError(f"GeckoTerminal returned empty OHLCV for {network}/{pool}")

    candles: List[Dict[str, Any]] = []
    for item in ohlcv_list:
        ts, o, h, l, c, v = item
        candles.append(
            {
                "timestamp": datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat(),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(v),
            }
        )
    return candles

def _synthetic_candles(source_key: str, days: int = DEFAULT_DAYS) -> List[Dict[str, Any]]:
    """Generate deterministic synthetic OHLCV candles when no live source exists."""
    candles: List[Dict[str, Any]] = []
    seed = sum(ord(ch) for ch in source_key)
    price = 1.0 + (seed % 100) / 10.0
    hours = days * 24
    for i in range(1, hours + 1):
        ts = _SYNTHETIC_EPOCH + timedelta(hours=i - 1)
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
    pairs_path: str = PRICE_PAIRS_PATH,
) -> List[Dict[str, Any]]:
    """
    Fetch OHLCV candles for a subnet token.

    Tries TaoMarketCap first when INDICATOR_USE_LIVE_PRICES=true, falls back to
    GeckoTerminal for explicitly mapped pools, then to the Blockmachine RPC
    alpha price, and finally to deterministic synthetic candles.
    """
    pairs = _load_price_pairs(pairs_path)
    sources = _price_sources_for_subnet(subnet_id, pairs)
    cache_key = str(subnet_id)

    cache = _load_json(cache_path) if use_cache else {}
    now = time.time()
    cached = cache.get(cache_key)
    if cached and (now - cached.get("cached_at", 0)) < CACHE_TTL_SECONDS:
        return cached.get("candles", [])

    candles: List[Dict[str, Any]] = []
    source = "unknown"
    error: Optional[str] = None

    if USE_LIVE_PRICES:
        for src in sources:
            try:
                if src["source"] == "taomarketcap":
                    candles = _fetch_tmc_subnet_candles(src["netuid"], days=days)
                    source = "taomarketcap"
                    break
                if src["source"] == "geckoterminal":
                    candles = _fetch_geckoterminal_ohlcv(
                        src["network"], src["pool"], days=days
                    )
                    source = "geckoterminal"
                    break
                if src["source"] == "blockmachine":
                    candles = _fetch_rpc_subnet_candles(src["netuid"], days=days)
                    source = "blockmachine"
                    break
            except Exception as exc:
                error = str(exc)
                # Continue to the next source in the tier.

    if not candles:
        synthetic_key = f"subnet-{subnet_id}"
        candles = _synthetic_candles(synthetic_key, days=days)
        source = "synthetic"

    if use_cache:
        cache[cache_key] = {
            "source": source,
            "cached_at": now,
            "fetched_at": _now_iso(),
            "error": error,
            "candles": candles,
        }
        _save_json(cache_path, cache)

    return candles
