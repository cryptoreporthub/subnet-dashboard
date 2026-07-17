"""Shared subnet feed for council picks, /api/subnets, and ops probes (§30-10, §33)."""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

SUBNETS_LOAD_TIMEOUT = float(os.environ.get("SUBNETS_LOAD_TIMEOUT_SECONDS", "25"))


def subnet_feed_meta(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Infer primary feed source for /api/subnets meta (§27-2)."""
    if not rows:
        return {"source": "registry", "sources": ["registry"]}
    live_bm = sum(
        1
        for r in rows
        if r.get("live") or str(r.get("source") or "").lower() == "blockmachine"
    )
    if live_bm > 0:
        sources = ["blockmachine"]
        if any(
            isinstance(r.get("sources"), list) and "taostats" in r["sources"] for r in rows
        ):
            sources.append("taostats")
        if any(
            isinstance(r.get("sources"), list) and "taomarketcap" in r["sources"] for r in rows
        ) or live_bm < len(rows):
            sources.append("taomarketcap")
        return {"source": "blockmachine", "sources": sources}
    tmc = sum(
        1
        for r in rows
        if str(r.get("source") or "").lower() == "taomarketcap"
        or (
            isinstance(r.get("sources"), list) and "taomarketcap" in r["sources"]
        )
    )
    if tmc > len(rows) // 2:
        return {"source": "taomarketcap", "sources": ["taomarketcap", "registry"]}
    return {"source": "registry", "sources": ["registry"]}


def _registry_rows() -> List[Dict[str, Any]]:
    path = os.environ.get("REGISTRY_PATH", "config/registry.json")
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return list(data.values())
    except Exception:
        pass
    return []


def _load_subnets_inner() -> List[Dict[str, Any]]:
    """Load subnet rows from live/TMC feeds (may hit network)."""
    from fetchers.taomarketcap import get_all_subnets
    from internal.subnet_names import enrich_subnet_rows

    live = get_all_subnets()
    if live:
        return enrich_subnet_rows(live)
    return enrich_subnet_rows(_registry_rows())


def load_subnets_source(timeout: float | None = None) -> List[Dict[str, Any]]:
    """Return subnets for /api/subnets with a hard timeout and registry fallback."""
    limit = SUBNETS_LOAD_TIMEOUT if timeout is None else timeout
    if limit <= 0:
        return _load_subnets_inner()
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_load_subnets_inner)
        try:
            return fut.result(timeout=limit)
        except FuturesTimeoutError:
            logger.warning(
                "subnet feed load timed out after %.0fs; using registry fallback",
                limit,
            )
        except Exception as exc:
            logger.warning("subnet feed load failed: %s; using registry fallback", exc)
    try:
        from internal.subnet_names import enrich_subnet_rows

        return enrich_subnet_rows(_registry_rows())
    except Exception:
        return _registry_rows()


def probe_feed_layers() -> Dict[str, Any]:
    """Cheap, non-blocking probe of subnet feed layers (no outbound network)."""
    from internal.live_subnets import CACHE_PATH

    registry_count = len(_registry_rows())
    live_cache = {
        "exists": False,
        "count": 0,
        "synced_at": None,
        "stale": True,
    }
    try:
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH, "r") as f:
                data = json.load(f)
            live_cache["exists"] = True
            live_cache["count"] = int(data.get("count") or len(data.get("subnets") or []))
            live_cache["synced_at"] = data.get("synced_at")
            live_cache["stale"] = not live_cache["count"]
    except Exception as exc:
        logger.debug("live cache probe failed: %s", exc)

    tmc_cache = {"exists": False, "count": 0}
    try:
        from fetchers.taomarketcap import get_cached, init_db

        init_db()
        cached = get_cached("all_subnets")
        if cached:
            subs = cached.get("subnets") or []
            tmc_cache = {"exists": True, "count": len(subs)}
    except Exception as exc:
        logger.debug("tmc cache probe failed: %s", exc)

    if live_cache["count"] > 0 and not live_cache["stale"]:
        effective_source = "blockmachine"
    elif tmc_cache["count"] > 0:
        effective_source = "taomarketcap"
    elif registry_count > 0:
        effective_source = "registry"
    else:
        effective_source = "none"

    return {
        "effective_source": effective_source,
        "registry_count": registry_count,
        "live_cache": live_cache,
        "tmc_cache": tmc_cache,
        "likely_total": max(live_cache["count"], tmc_cache["count"], registry_count),
    }


def get_council_subnet_feed() -> Tuple[List[Dict[str, Any]], str]:
    """Return enriched subnets + source label for pick and judge paths."""
    try:
        rows = load_subnets_source()
        if rows:
            meta = subnet_feed_meta(rows)
            return rows, str(meta.get("source") or "taomarketcap")
    except Exception as exc:
        logger.debug("council feed unavailable: %s", exc)

    try:
        from fetchers.merged_data import get_merged_subnet_data
        from internal.subnet_names import enrich_subnet_rows

        merged = get_merged_subnet_data()
        if merged:
            rows = enrich_subnet_rows(merged)
            if rows:
                return rows, "merged"
    except Exception as exc:
        logger.warning("merged feed unavailable: %s", exc)

    return [], "none"


def load_pick_subnets() -> List[Dict[str, Any]]:
    """Subnet rows for daily pick / story paths (§29-7)."""
    rows, _source = get_council_subnet_feed()
    return rows


def warm_subnet_feed() -> None:
    """Boot-time warmup: prime TMC/live caches so first /api/subnets is fast."""
    try:
        rows = load_subnets_source()
        meta = subnet_feed_meta(rows)
        logger.info(
            "subnet feed warmup: %d rows source=%s",
            len(rows or []),
            meta.get("source"),
        )
    except Exception as exc:
        logger.warning("subnet feed warmup failed: %s", exc)
