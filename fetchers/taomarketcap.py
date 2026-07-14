Title: 

URL Source: https://raw.githubusercontent.com/cryptoreporthub/subnet-dashboard/main/fetchers/taomarketcap.py

Markdown Content:
"""
Live data fetcher for taomarketcap.com public API v1.
Fetches all subnets from /public/v1/subnets/table/, caches in SQLite for 5 min.
Handles both list and dict ({"subnets": [...]}) API responses.
Now paginates through all pages to get the full ~129 subnets.
"""
import requests
import json
import sqlite3
import os
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = "data/subnets.db"
CACHE_DURATION = timedelta(minutes=5)
API_BASE = "https://api.taomarketcap.com/public/v1/subnets/table/"
PAGE_SIZE = 10
MAX_PAGES = 5
FETCH_DEADLINE_SEC = 25

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
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
    conn = sqlite3.connect(DB_PATH, timeout=10)
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
    conn = sqlite3.connect(DB_PATH, timeout=10)
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
    if isinstance(netuid, dict):
        netuid = netuid.get("id") or netuid.get("netuid") or netuid.get("subnet") or 0
    try:
        netuid = int(netuid)
    except (TypeError, ValueError):
        netuid = 0
    name = row.get("name") or f"SN{netuid}"
    if name in ("Unknown", "None", "deprecated"):
        name = f"SN{netuid}"
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
        "price_change_24h": round(row.get("price_difference_day", row.get("price_difference", 0)), 4),
        "price_change_7d": round(row.get("price_difference_week", 0), 4),
        "price_change_30d": round(row.get("price_difference_month", 0), 4),
        "status": "active" if row.get("subnet") is not None else "unknown",
        "stake": round(row.get("total_stake", row.get("stake", 0)), 4),
        "total_stake": round(row.get("total_stake", row.get("stake", 0)), 4),
        "delegation_count": row.get("delegated", row.get("delegation_count", 0)),
        "owner_count": row.get("owners", row.get("owner_count", 0)),
        "registration_cost": round(row.get("cost", row.get("registration_cost", 0)), 4),
        "age_blocks": row.get("blocks_since_registration", row.get("age_blocks", row.get("age", 0))),
        "symbol": row.get("symbol", ""),
        "marketcap_rank": row.get("marketcap_rank", 0),
    }

def fetch_all_subnets_from_api() -> Optional[List[Dict]]:
    """Fetch ALL subnets from taomarketcap.com public API.

    The upstream API ignores the `?page=` param and returns the same
    full dataset on every call, so naive pagination duplicates rows.
    We dedupe by netuid and stop as soon as a page adds no new subnets.
    """
    all_subnets = []
    seen_netuids = set()
    started = time.monotonic()
    for page in range(1, MAX_PAGES + 1):
        if time.monotonic() - started > FETCH_DEADLINE_SEC:
            logger.warning("Subnet fetch deadline (%ss) reached on page %d", FETCH_DEADLINE_SEC, page)
            break
        try:
            url = f"{API_BASE}?page={page}"
            logger.info("Fetching subnets page %d from %s", page, url)
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200:
                logger.warning("API page %d returned %s", page, resp.status_code)
                break

            payload = resp.json()
            if isinstance(payload, dict):
                rows = payload.get("subnets") or payload.get("data") or payload.get("results")
                if rows is None:
                    break
                if not isinstance(rows, list):
                    break
            elif isinstance(payload, list):
                rows = payload
            else:
                break

            if not rows:
                break

            new_count = 0
            for row in rows:
                parsed = _parse_subnet_row(row)
                netuid = parsed.get("netuid")
                if netuid in seen_netuids:
                    continue
                seen_netuids.add(netuid)
                all_subnets.append(parsed)
                new_count += 1

            logger.info("Page %d: %d new / %d parsed (total unique: %d)", page, new_count, len(rows), len(all_subnets))

            if new_count == 0:
                logger.info("No new subnets on page %d; stopping pagination", page)
                break

            if len(rows) < PAGE_SIZE:
                break

            if page < MAX_PAGES and time.monotonic() - started < FETCH_DEADLINE_SEC:
                time.sleep(1)
        except Exception as e:
            logger.warning("Error fetching page %d: %s", page, e)
            break

    deduped = {}
    for s in all_subnets:
        deduped.setdefault(s.get("netuid"), s)
    all_subnets = list(deduped.values())

    if all_subnets:
        logger.info("Fetched %d unique subnets across all pages", len(all_subnets))
        return all_subnets
    return None

def get_all_subnets() -> List[Dict]:
    """Return all subnets.\n\n    Phase B1: prefer the live on-chain feed (internal.live_subnets), which merges\n    Bittensor chain data over the committed registry. Falls back to the original\n    TaoMarketCap scrape if the live feed is unavailable. See docs/EXTREME_AUDIT.md #1.\n    """\n    try:\n        from internal.live_subnets import get_live_subnets\n        live = get_live_subnets()\n        if live:\n            return live\n    except Exception as exc:  # pragma: no cover - defensive\n        logger.warning("Live subnet feed unavailable, using TaoMarketCap: %s", exc)\n    return _get_all_subnets_tao()\n\n\ndef _get_all_subnets_tao() -> List[Dict]:\n    """Original TaoMarketCap implementation (cache + fallback)."""    init_db()
    cached = get_cached("all_subnets")
    if cached:
        return cached.get("subnets", [])
    raw = fetch_all_subnets_from_api()
    if raw:
        set_cache("all_subnets", {"subnets": raw})
        return raw
    conn = sqlite3.connect(DB_PATH, timeout=10)
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
    return []

def get_subnet_data(netuid: int) -> Optional[Dict]:
    """Get data for a single subnet by netuid."""
    subnets = get_all_subnets()
    for s in subnets:
        if s.get("netuid") == netuid:
            return s
    return None
