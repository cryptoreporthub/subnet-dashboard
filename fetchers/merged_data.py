"""Merged data layer — combines Blockmachine, TaoStats, and TaoMarketCap.

Priority: Blockmachine (primary) > TaoStats (supplementary) > TaoMarketCap (fallback).
Caches merged result in SQLite with 2-min TTL.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fetchers._sqlite import db_conn

logger = logging.getLogger(__name__)
MERGED_DB_PATH = os.environ.get("MERGED_DB_PATH", "data/merged_cache.db")
MERGED_CACHE_TTL = timedelta(minutes=2)
_merged_by_netuid: Dict[int, Dict[str, Any]] = {}
_merged_index_at: float = 0.0


def _init_db():
    os.makedirs(os.path.dirname(MERGED_DB_PATH) or ".", exist_ok=True)
    with db_conn(MERGED_DB_PATH) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS merged_cache (
        key TEXT PRIMARY KEY, data TEXT, last_updated TIMESTAMP)"""
        )
        conn.commit()


def _get_cached(key):
    with db_conn(MERGED_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT data, last_updated FROM merged_cache WHERE key = ?", (key,))
        row = c.fetchone()
    if row:
        data_str, last_updated = row
        updated = datetime.fromisoformat(last_updated)
        if datetime.now() - updated < MERGED_CACHE_TTL:
            return json.loads(data_str)
    return None


def _set_cache(key, data):
    global _merged_by_netuid, _merged_index_at
    with db_conn(MERGED_DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO merged_cache (key, data, last_updated) VALUES (?, ?, ?)",
            (key, json.dumps(data), datetime.now().isoformat()),
        )
        conn.commit()
    if key == "all_merged" and isinstance(data, dict):
        subnets = data.get("subnets") or []
        _merged_by_netuid = {int(s["netuid"]): s for s in subnets if s.get("netuid") is not None}
        _merged_index_at = time.time()


def _refresh_index_from_cache() -> None:
    global _merged_by_netuid, _merged_index_at
    cached = _get_cached("all_merged")
    if cached:
        subnets = cached.get("subnets") or []
        _merged_by_netuid = {int(s["netuid"]): s for s in subnets if s.get("netuid") is not None}
        _merged_index_at = time.time()


def _merge_subnet(bm, ts, tmc):
    netuid = (bm or ts or tmc or {}).get("netuid", 0)
    name = (
        (bm.get("name") if bm and bm.get("name") and not str(bm.get("name", "")).startswith("SN") else None)
        or (ts.get("name") if ts and ts.get("name") else None)
        or f"SN{netuid}"
    )
    try:
        from internal.subnet_names import resolve_subnet_name
        name = resolve_subnet_name(
            int(netuid),
            tmc_name=tmc.get("name") if tmc else None,
            use_taostats=False,
        )
    except Exception:
        if tmc and tmc.get("name") and str(tmc.get("name")).lower() not in ("unknown", "deprecated", ""):
            name = tmc["name"]
    symbol = tmc.get("symbol", "") if tmc else ""
    price = (
        bm.get("price") if bm and bm.get("price")
        else ts.get("price") if ts and ts.get("price")
        else tmc.get("price", 0) if tmc else 0
    )
    price_change_24h = (
        ts.get("price_change_1d") if ts and ts.get("price_change_1d")
        else tmc.get("price_change_24h", 0) if tmc else 0
    )
    price_change_7d = (
        ts.get("price_change_7d") if ts and ts.get("price_change_7d")
        else tmc.get("price_change_7d", 0) if tmc else 0
    )
    price_change_30d = (
        ts.get("price_change_30d") if ts and ts.get("price_change_30d")
        else tmc.get("price_change_30d", 0) if tmc else 0
    )
    price_change_1h = ts.get("price_change_1h", 0) if ts else 0
    stake = (
        bm.get("stake") if bm and bm.get("stake")
        else tmc.get("stake", 0) if tmc else 0
    )
    total_stake = (
        bm.get("total_stake") if bm and bm.get("total_stake")
        else tmc.get("total_stake", stake) if tmc else stake
    )
    emission = (
        bm.get("emission") if bm and bm.get("emission")
        else tmc.get("emission", 0) if tmc else 0
    )
    liquidity = (
        bm.get("liquidity") if bm and bm.get("liquidity")
        else ts.get("liquidity", 0) if ts else 0
    )
    root_prop = (
        bm.get("root_prop") if bm and bm.get("root_prop")
        else ts.get("root_prop", 0) if ts else 0
    )
    total_tao = bm.get("total_tao", 0) if bm else ts.get("total_tao", 0) if ts else 0
    total_alpha = bm.get("total_alpha", 0) if bm else ts.get("total_alpha", 0) if ts else 0
    buys_24hr = (
        bm.get("buys_24hr", 0) if bm and bm.get("buys_24hr")
        else ts.get("buys_24hr", 0) if ts else 0
    )
    sells_24hr = (
        bm.get("sells_24hr", 0) if bm and bm.get("sells_24hr")
        else ts.get("sells_24hr", 0) if ts else 0
    )
    buy_volume_24h = (
        bm.get("buy_volume_24h", 0) if bm and bm.get("buy_volume_24h")
        else ts.get("buy_volume_24h", 0) if ts else 0
    )
    sell_volume_24h = (
        bm.get("sell_volume_24h", 0) if bm and bm.get("sell_volume_24h")
        else ts.get("sell_volume_24h", 0) if ts else 0
    )
    fear_and_greed = ts.get("fear_and_greed", 0) if ts else 0
    seven_day_prices = ts.get("seven_day_prices", []) if ts else []
    volume = tmc.get("volume", 0) if tmc else 0
    market_cap = tmc.get("market_cap", tmc.get("marketcap", 0)) if tmc else 0
    marketcap_rank = tmc.get("marketcap_rank", 0) if tmc else 0
    delegation_count = tmc.get("delegation_count", tmc.get("delegated", 0)) if tmc else 0
    owner_count = tmc.get("owner_count", tmc.get("owners", 0)) if tmc else 0
    registration_cost = (
        bm.get("registration_cost") if bm and bm.get("registration_cost")
        else tmc.get("registration_cost", tmc.get("cost", 0)) if tmc else 0
    )
    age_blocks = (
        bm.get("age_blocks") if bm and bm.get("age_blocks")
        else tmc.get("age_blocks", tmc.get("blocks_since_registration", 0)) if tmc else 0
    )
    sources = []
    if bm and not bm.get("degraded"):
        sources.append("blockmachine")
    if ts:
        sources.append("taostats")
    if tmc:
        sources.append("taomarketcap")
    return {
        "netuid": netuid, "name": name, "symbol": symbol,
        "price": round(price, 8) if price else 0,
        "price_change_1h": round(price_change_1h, 4),
        "price_change_24h": round(price_change_24h, 4),
        "price_change_7d": round(price_change_7d, 4),
        "price_change_30d": round(price_change_30d, 4),
        "stake": round(stake, 4) if stake else 0,
        "total_stake": round(total_stake, 4) if total_stake else 0,
        "emission": round(emission, 4) if emission else 0,
        "liquidity": round(liquidity, 4) if liquidity else 0,
        "total_tao": round(total_tao, 4) if total_tao else 0,
        "total_alpha": round(total_alpha, 4) if total_alpha else 0,
        "root_prop": round(root_prop, 4) if root_prop else 0,
        "buys_24hr": buys_24hr, "sells_24hr": sells_24hr,
        "buy_volume_24h": round(buy_volume_24h, 4) if buy_volume_24h else 0,
        "sell_volume_24h": round(sell_volume_24h, 4) if sell_volume_24h else 0,
        "fear_and_greed": round(fear_and_greed, 2) if fear_and_greed else 0,
        "seven_day_prices": seven_day_prices,
        "volume": round(volume, 2) if volume else 0,
        "market_cap": round(market_cap, 2) if market_cap else 0,
        "marketcap_rank": marketcap_rank,
        "delegation_count": delegation_count,
        "owner_count": owner_count,
        "registration_cost": round(registration_cost, 4) if registration_cost else 0,
        "age_blocks": age_blocks,
        "status": "active",
        "sources": sources,
    }


def get_merged_subnet_data():
    cached = _get_cached("all_merged")
    if cached:
        return cached.get("subnets", [])
    # Layer 1: Blockmachine
    bm_subnets = []
    bm_by_netuid = {}
    try:
        from internal.chain_client import get_default_client
        client = get_default_client()
        if client.is_healthy():
            bm_subnets = client.get_all_subnet_data()
            bm_by_netuid = {s["netuid"]: s for s in bm_subnets}
            logger.info("Merged: %d subnets from Blockmachine", len(bm_subnets))
        else:
            logger.warning("Merged: Blockmachine unhealthy")
    except Exception as exc:
        logger.warning("Merged: Blockmachine failed: %s", exc)
    # Layer 3: TaoMarketCap
    tmc_subnets = []
    tmc_by_netuid = {}
    try:
        from fetchers.taomarketcap import get_all_subnets
        tmc_subnets = get_all_subnets()
        tmc_by_netuid = {s.get("netuid"): s for s in tmc_subnets}
        logger.info("Merged: %d subnets from TaoMarketCap", len(tmc_subnets))
    except Exception as exc:
        logger.warning("Merged: TaoMarketCap failed: %s", exc)
    all_netuids = set(bm_by_netuid.keys()) | set(tmc_by_netuid.keys())
    if not all_netuids:
        logger.error("Merged: no data from any source!")
        return []
    sorted_netuids = sorted(all_netuids)
    # Layer 2: TaoStats
    ts_by_netuid = {}
    try:
        from fetchers.taostats_client import get_top_subnet_metrics, get_cached_metrics, is_available
        if is_available():
            ts_by_netuid = get_top_subnet_metrics(list(all_netuids), limit=20)
        for netuid in all_netuids:
            if netuid not in ts_by_netuid:
                cached_ts = get_cached_metrics(netuid)
                if cached_ts:
                    ts_by_netuid[netuid] = cached_ts
        logger.info("Merged: %d metrics from TaoStats", len(ts_by_netuid))
    except Exception as exc:
        logger.warning("Merged: TaoStats failed: %s", exc)
    # Merge
    merged = []
    for netuid in sorted_netuids:
        bm = bm_by_netuid.get(netuid)
        ts = ts_by_netuid.get(netuid)
        tmc = tmc_by_netuid.get(netuid)
        merged.append(_merge_subnet(bm, ts, tmc))
    logger.info("Merged: %d total subnets", len(merged))
    _set_cache("all_merged", {"subnets": merged})
    return merged


def get_merged_subnet(netuid):
    global _merged_by_netuid, _merged_index_at
    if not _merged_by_netuid or (time.time() - _merged_index_at) > MERGED_CACHE_TTL.total_seconds():
        _refresh_index_from_cache()
    try:
        n = int(netuid)
    except (TypeError, ValueError):
        return None
    hit = _merged_by_netuid.get(n)
    if hit is not None:
        return hit
    get_merged_subnet_data()
    return _merged_by_netuid.get(n)

_init_db()
