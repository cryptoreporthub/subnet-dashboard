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
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    from fetchers._sqlite import db_conn

    with db_conn(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS taostats_cache (
        netuid INTEGER PRIMARY KEY, data TEXT, last_updated TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS rotation_state (
        id INTEGER PRIMARY KEY DEFAULT 0, last_offset INTEGER DEFAULT 0,
        last_rotation TIMESTAMP, CONSTRAINT single_row CHECK (id = 0))""")
        c.execute("INSERT OR IGNORE INTO rotation_state (id, last_offset, last_rotation) VALUES (0, 0, '2025-01-01T00:00:00Z')")
        conn.commit()


def _get_cached(netuid):
    from fetchers._sqlite import db_conn

    with db_conn(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT data, last_updated FROM taostats_cache WHERE netuid = ?", (netuid,))
        row = c.fetchone()
    if row:
        data_str, last_updated = row
        updated = datetime.fromisoformat(last_updated)
        if datetime.now() - updated < CACHE_TTL:
            return json.loads(data_str)
    return None


def _set_cache(netuid, data):
    from fetchers._sqlite import db_conn

    with db_conn(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO taostats_cache (netuid, data, last_updated) VALUES (?, ?, ?)",
                  (netuid, json.dumps(data), datetime.now().isoformat()))
        conn.commit()


def _get_rotation_offset():
    from fetchers._sqlite import db_conn

    with db_conn(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT last_offset FROM rotation_state WHERE id = 0")
        row = c.fetchone()
    return row[0] if row else 0


def _set_rotation_offset(offset):
    from fetchers._sqlite import db_conn

    with db_conn(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE rotation_state SET last_offset = ?, last_rotation = ? WHERE id = 0",
                  (offset, datetime.now().isoformat()))
        conn.commit()


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


def get_subnet_metrics(netuid):
    cached = _get_cached(netuid)
    if cached:
        return cached
    if not TAOSTATS_API_KEY:
        logger.debug("TaoStats API key not set, skipping")
        return None
    _rate_limit()
    try:
        data = _api_get("/dtao/pool/latest/v1", {"netuid": netuid})
        if not data:
            return None
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


def _api_get(path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    """Shared GET for TaoStats REST (api/v1 prefix)."""
    if not TAOSTATS_API_KEY:
        return None
    _rate_limit()
    try:
        base = TAOSTATS_API_BASE.rstrip("/")
        if not base.endswith("/api/v1"):
            base = f"{base}/api/v1"
        url = f"{base}{path}"
        headers = {"Authorization": f"Bearer {TAOSTATS_API_KEY}", "Accept": "application/json"}
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code == 429:
            logger.warning("TaoStats rate limited on %s", path)
            return None
        if resp.status_code != 200:
            logger.debug("TaoStats %s returned %d", path, resp.status_code)
            return None
        return resp.json()
    except Exception as exc:
        logger.debug("TaoStats GET %s failed: %s", path, exc)
        return None


def get_subnet_identity(netuid: int) -> Optional[Any]:
    return _api_get(f"/subnets/{netuid}/identity")


def get_subnet_owner(netuid: int) -> Optional[Any]:
    return _api_get(f"/subnets/{netuid}/owner")


def get_delegation_events(
    *,
    netuid: Optional[int] = None,
    nominator: Optional[str] = None,
    action: str = "all",
    limit: int = 50,
) -> Optional[Any]:
    params: Dict[str, Any] = {"limit": limit, "action": action}
    if netuid is not None:
        params["netuid"] = netuid
    if nominator:
        params["nominator"] = nominator
    return _api_get("/delegation/v1", params)


def get_transfers(
    *,
    from_wallet: Optional[str] = None,
    to_wallet: Optional[str] = None,
    limit: int = 50,
) -> Optional[Any]:
    params: Dict[str, Any] = {"limit": limit}
    if from_wallet:
        params["from"] = from_wallet
    if to_wallet:
        params["to"] = to_wallet
    return _api_get("/transfer/v1", params)


def get_account(wallet: str) -> Optional[Any]:
    return _api_get(f"/account/{wallet}")


def get_subnet_delegation_flow(netuid: int, limit: int = 50) -> Optional[Any]:
    return _api_get(f"/subnets/{netuid}/delegations", {"limit": limit})


def get_dtao_pool_latest(netuid: int) -> Optional[Any]:
    return _api_get("/dtao/pool/latest/v1", {"netuid": netuid})


def get_subnet_registration_cost(netuid: int) -> Optional[Any]:
    return _api_get(f"/subnets/{netuid}/registration")


def get_tao_price() -> Optional[Any]:
    return _api_get("/tao/price")


def get_tao_price_history(limit: int = 168) -> Optional[Any]:
    return _api_get("/tao/price/history", {"limit": limit})


_init_db()
