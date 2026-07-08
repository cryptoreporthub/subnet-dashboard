"""TaoStats API client — supplementary data source (Layer 2).

Free tier: 5 calls/min. Fetches derived metrics that Blockmachine can't provide:
- fear_and_greed index (proprietary TaoStats sentiment metric)
- seven_day_prices (pre-computed 7-day price array)
- root_prop, liquidity, buys_24hr, sells_24hr

Rotates through subnets so all 129 get covered over time.
Caches results in SQLite with 10-min TTL.
"""

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

TAOSTATS_API_BASE = os.environ.get("TAOSTATS_API_BASE", "https://api.taostats.io")
TAOSTATS_API_KEY = os.environ.get("TAOSTATS_API_KEY", "")
RATE_LIMIT_CALLS_PER_MIN = 5
CACHE_TTL = timedelta(minutes=10)
DB_PATH = os.environ.get("TAOSTATS_DB_PATH", "data/taostats_cache.db")
_call_timestamps: List[float] = []


def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS taostats_cache (
        netuid INTEGER PRIMARY KEY, data TEXT, last_updated TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS rotation_state (
        id INTEGER PRIMARY KEY DEFAULT 0, last_offset INTEGER DEFAULT 0,
        last_rotation TIMESTAMP, CONSTRAINT single_row CHECK (id = 0))""")
    c.execute("INSERT OR IGNORE INTO rotation_state (id, last_offset, last_rotation) VALUES (0, 0, '2025-01-01T00:00:00Z')")
    conn.commit()
    conn.close()


def _rate_limit():
    global _call_timestamps
    now = time.time()
    _call_timestamps = [t for t in _call_timestamps if now - t < 60.0]
    if len(_call_timestamps) >= RATE_LIMIT_CALLS_PER_MIN:
        wait = 60.0 - (now - _call_timestamps[0]) + 0.1
        if wait > 0:
            logger.debug("TaoStats rate limit: waiting %.1fs", wait)
            time.sleep(wait)
    _call_timestamps.append(time.time())


def _get_cached(netuid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT data, last_updated FROM taostats_cache WHERE netuid = ?", (netuid,))
    row = c.fetchone()
    conn.close()
    if row:
        data_str, last_updated = row
        updated = datetime.fromisoformat(last_updated)
        if datetime.now() - updated < CACHE_TTL:
            return json.loads(data_str)
    return None


def _set_cache(netuid, data):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO taostats_cache (netuid, data, last_updated) VALUES (?, ?, ?)",
              (netuid, json.dumps(data), datetime.now().isoformat()))
    conn.commit()
    conn.close()


def _get_rotation_offset():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT last_offset FROM rotation_state WHERE id = 0")
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0


def _set_rotation_offset(offset):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE rotation_state SET last_offset = ?, last_rotation = ? WHERE id = 0",
              (offset, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_subnet_metrics(netuid):
    cached = _get_cached(netuid)
    if cached:
        return cached
    if not TAOSTATS_API_KEY:
        logger.debug("TaoStats API key not set, skipping")
        return None
    _rate_limit()
    try:
        url = f"{TAOSTATS_API_BASE}/dtao/pool/latest/v1"
        headers = {"Authorization": f"Bearer {TAOSTATS_API_KEY}", "Accept": "application/json"}
        resp = requests.get(url, params={"netuid": netuid}, headers=headers, timeout=15)
        if resp.status_code == 429:
            logger.warning("TaoStats rate limited on netuid %d", netuid)
            return None
        if resp.status_code != 200:
            logger.debug("TaoStats API returned %d for netuid %d", resp.status_code, netuid)
            return None
        data = resp.json()
        if isinstance(data, dict):
            records = data.get("data", data.get("results", [data]))
        elif isinstance(data, list):
            records = data
        else:
            return None
        if not records:
            return None
        r = records[0] if isinstance(records, list) else records
        metrics = {
            "netuid": netuid,
            "fear_and_greed": float(r.get("fear_and_greed", 0) or 0),
            "seven_day_prices": r.get("seven_day_prices", r.get("seven_day_prices_arr", [])),
            "price_change_1h": float(r.get("price_change_1h", r.get("delta_1h", 0)) or 0),
            "price_change_1d": float(r.get("price_change_1d", r.get("delta_1d", r.get("price_difference", 0))) or 0),
            "price_change_7d": float(r.get("price_change_7d", r.get("delta_7d", r.get("price_difference_week", 0))) or 0),
            "price_change_30d": float(r.get("price_change_30d", r.get("delta_30d", 0)) or 0),
            "root_prop": float(r.get("root_prop", 0) or 0),
            "liquidity": float(r.get("liquidity", r.get("total_tao", 0)) or 0),
            "buys_24hr": int(r.get("buys_24hr", r.get("buys", 0)) or 0),
            "sells_24hr": int(r.get("sells_24hr", r.get("sells", 0)) or 0),
            "buy_volume_24h": float(r.get("buy_volume_24hr", r.get("buy_volume", 0)) or 0),
            "sell_volume_24h": float(r.get("sell_volume_24hr", r.get("sell_volume", 0)) or 0),
            "source": "taostats",
        }
        _set_cache(netuid, metrics)
        return metrics
    except Exception as exc:
        logger.debug("TaoStats fetch failed for netuid %d: %s", netuid, exc)
        return None


def get_top_subnet_metrics(netuids, limit=20):
    if not TAOSTATS_API_KEY:
        logger.debug("TaoStats API key not set, skipping batch fetch")
        return {}
    if not netuids:
        return {}
    offset = _get_rotation_offset()
    selected = []
    for i in range(limit):
        idx = (offset + i) % len(netuids)
        selected.append(netuids[idx])
    new_offset = (offset + limit) % len(netuids)
    _set_rotation_offset(new_offset)
    results = {}
    for netuid in selected:
        metrics = get_subnet_metrics(netuid)
        if metrics:
            results[netuid] = metrics
    logger.info("TaoStats batch: fetched %d/%d subnets (offset %d -> %d, total %d)",
                len(results), limit, offset, new_offset, len(netuids))
    return results


def get_cached_metrics(netuid):
    return _get_cached(netuid)


def is_available():
    return bool(TAOSTATS_API_KEY)

_init_db()
