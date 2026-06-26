"""
Live data fetcher for taomarketcap.com public API v1.
Fetches all subnets from /public/v1/subnets/table/, caches in SQLite for 5 min.
Handles both list and dict ({"subnets": [...]}) API responses.
"""
import requests
import json
import sqlite3
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = "data/subnets.db"
CACHE_DURATION = timedelta(minutes=5)


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS subnets_cache (
        key TEXT PRIMARY KEY,
        data TEXT,
        last_updated TIMESTAMP
    )"""
    )
    conn.commit()
    conn.close()


def get_cached(key: str) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT data, last_updated FROM subnets_cache WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    if row:
        data_str, last_updated = row
        updated = datetime.fromisoformat(last_updated)
        if datetime.now() - updated < CACHE_DURATION:
            return json.loads(data_str)
    return None


def set_cache(key: str, data: Dict):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO subnets_cache (key, data, last_updated) VALUES (?, ?, ?)",
        (key, json.dumps(data), datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def _parse_subnet_row(row: dict) -> Dict:
    """Normalise a raw API row into our standard subnet dict."""
    netuid = row.get("subnet", 0)
    name = row.get("name") or f"SN{netuid}"
    if name in ("Unknown", "None", "deprecated"):
        name = f"SN{netuid}"

    # approximate APY from 7-day change (crude weekly → annual)
    pchg_w = row.get("price_difference_week", 0) or 0
    apy = round(pchg_w * 52.0 / 100.0, 2)

    return {
        "netuid": netuid,
        "name": name,
        "emission": round(row.get("emission", 0), 4),
        "apy": apy,
        "volume": round(row.get("volume", 0), 2),
        "market_cap": round(row.get("marketcap", 0), 2),
        "price": round(row.get("price", 0), 8),
        "price_change_24h": round(row.get("price_difference_day", 0), 2),
        "price_change_7d": round(row.get("price_difference_week", 0), 2),
        "price_change_30d": round(row.get("price_difference_month", 0), 2),
        "status": "active" if row.get("is_active", False) else "inactive",
        "sector": "General",
        "circulating_supply": row.get("circulating_supply", 0),
        "fdv": row.get("fdv", 0),
        "tao_liquidity": row.get("tao_liquidity", 0),
        "alpha_liquidity": row.get("alpha_liquidity", 0),
        "market_cap_rank": row.get("marketcap_rank"),
        "last_updated": datetime.now().isoformat(),
    }


def fetch_all_subnets_from_api() -> Optional[List[Dict]]:
    """Fetch all subnets from taomarketcap.com public API (unauthenticated, 10 req/min).

    Handles both:
      - direct list response:  [{...}, {...}]
      - dict wrapper:          {"subnets": [{...}, {...}], ...}
    """
    try:
        url = "https://api.taomarketcap.com/public/v1/subnets/table/"
        logger.info("Fetching subnets from %s", url)
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            logger.warning("API returned %s", resp.status_code)
            return None

        payload = resp.json()
        logger.info("API response type: %s", type(payload).__name__)

        # Normalise: unwrap dict wrapper if present
        if isinstance(payload, dict):
            rows = payload.get("subnets") or payload.get("data") or payload.get("results")
            if rows is None:
                logger.warning("dict response lacks known key; keys=%s", list(payload.keys()))
                return None
            if not isinstance(rows, list):
                logger.warning("'subnets' value is not a list (%s)", type(rows))
                return None
        elif isinstance(payload, list):
            rows = payload
        else:
            logger.warning("Unexpected API response type: %s", type(payload))
            return None

        subnets = [_parse_subnet_row(row) for row in rows]
        logger.info("Parsed %d subnets from API", len(subnets))
        return subnets
    except Exception as e:
        logger.error("Error fetching subnets: %s", e)
        return None


def get_all_subnets() -> List[Dict]:
    """Return all subnets (cached, 5 min TTL). Falls back to stale cache or static data."""
    init_db()

    cached = get_cached("all_subnets")
    if cached:
        return cached.get("subnets", [])

    raw = fetch_all_subnets_from_api()
    if raw:
        set_cache("all_subnets", {"subnets": raw})
        return raw

    # stale fallback – try reading even expired cache
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT data FROM subnets_cache WHERE key = ?", ("all_subnets",))
    row = c.fetchone()
    conn.close()
    if row:
        cached_data = json.loads(row[0]).get("subnets", [])
        if cached_data:
            logger.info("Returning %d subnets from stale cache", len(cached_data))
            return cached_data

    logger.warning("No cache available, returning static fallback")
    return [
        {
            "netuid": 29,
            "name": "Coldint",
            "emission": 3.0,
            "apy": 42.5,
            "volume": 1250000,
            "market_cap": 45000000,
            "price": 28.50,
            "price_change_24h": 12.3,
            "status": "active",
            "sector": "AI/ML",
        },
        {
            "netuid": 19,
            "name": "Inference",
            "emission": 2.1,
            "apy": 38.2,
            "volume": 980000,
            "market_cap": 32000000,
            "price": 15.20,
            "price_change_24h": 8.7,
            "status": "active",
            "sector": "AI/ML",
        },
        {
            "netuid": 12,
            "name": "Compute",
            "emission": 1.8,
            "apy": 35.1,
            "volume": 750000,
            "market_cap": 28000000,
            "price": 12.40,
            "price_change_24h": 5.2,
            "status": "active",
            "sector": "Compute",
        },
    ]


def get_subnet_data(netuid: int) -> Optional[Dict]:
    for sn in get_all_subnets():
        if sn["netuid"] == netuid:
            return sn
    return None