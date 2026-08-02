"""Shared subnet feed for council picks, /api/subnets, and ops probes (§30-10, §33)."""

from __future__ import annotations

import json
import logging
import os
import threading
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


def registry_subnet_rows() -> List[Dict[str, Any]]:
    """Instant local subnet rows — no outbound network (hydrate / timeout fallback)."""
    return _registry_rows()


def _load_subnets_inner() -> List[Dict[str, Any]]:
    """Load subnet rows from live/TMC feeds (may hit network)."""
    from fetchers.taomarketcap import get_all_subnets
    from internal.subnet_names import enrich_subnet_rows

    live = get_all_subnets()
    if live:
        return enrich_subnet_rows(live)
    return enrich_subnet_rows(_registry_rows())


def _registry_fallback_rows() -> List[Dict[str, Any]]:
    try:
        from internal.subnet_names import enrich_subnet_rows

        return enrich_subnet_rows(_registry_rows())
    except Exception:
        return _registry_rows()


def _on_pool_thread() -> bool:
    """True when already on a worker thread (e.g. asyncio.to_thread)."""
    return threading.current_thread() is not threading.main_thread()


def load_subnets_source(timeout: float | None = None) -> List[Dict[str, Any]]:
    """Return subnets for /api/subnets with a hard timeout and registry fallback."""
    limit = SUBNETS_LOAD_TIMEOUT if timeout is None else timeout
    if limit <= 0:
        return _load_subnets_inner()
    # Outer asyncio.wait_for owns the deadline — avoid nested ThreadPoolExecutor.
    if _on_pool_thread():
        try:
            return _load_subnets_inner()
        except Exception as exc:
            logger.warning(
                "subnet feed load failed on worker thread: %s; using registry fallback",
                exc,
            )
            return _registry_fallback_rows()
    pool = ThreadPoolExecutor(max_workers=1)
    try:
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
    finally:
        # wait=False: timed-out live fetch must not wedge hydrate APIs (Fly 1-worker).
        pool.shutdown(wait=False, cancel_futures=True)
    return _registry_fallback_rows()


def _feed_layers_from_freshness(remote: Dict[str, Any]) -> Dict[str, Any]:
    """Map worker /api/data-freshness into probe_feed_layers shape."""
    subnet_count = int(remote.get("subnet_count") or 0)
    tmc_count = int(remote.get("tmc_cache_count") or 0)
    registry_count = int(remote.get("registry_count") or 0)
    effective = str(remote.get("effective_source") or "none")
    return {
        "effective_source": effective,
        "registry_count": registry_count,
        "live_cache": {
            "exists": subnet_count > 0 or bool(remote.get("last_sync")),
            "count": subnet_count,
            "synced_at": remote.get("last_sync"),
            "stale": bool(remote.get("stale")),
        },
        "tmc_cache": {"exists": tmc_count > 0, "count": tmc_count},
        "likely_total": int(
            remote.get("effective_total") or max(subnet_count, tmc_count, registry_count)
        ),
    }


def probe_feed_layers() -> Dict[str, Any]:
    """Cheap, non-blocking probe of subnet feed layers (no outbound network)."""
    try:
        from internal.data_volume import worker_data_freshness

        remote = worker_data_freshness()
        if remote:
            return _feed_layers_from_freshness(remote)
    except Exception:
        pass
    from internal.live_subnets import _cache_path

    cache_file = _cache_path()
    registry_count = len(_registry_rows())
    live_cache = {
        "exists": False,
        "count": 0,
        "synced_at": None,
        "stale": True,
    }
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r") as f:
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


def get_council_subnet_feed(timeout: float | None = None) -> Tuple[List[Dict[str, Any]], str]:
    """Return enriched subnets + source label for pick and judge paths."""
    try:
        rows = load_subnets_source(timeout=timeout)
        if rows:
            meta = subnet_feed_meta(rows)
            return rows, str(meta.get("source") or "taomarketcap")
    except Exception as exc:
        logger.debug("council feed unavailable: %s", exc)

    rows = _registry_fallback_rows()
    if rows:
        return rows, "registry"
    return [], "none"


def load_subnets_for_display(timeout: float = 4.0) -> List[Dict[str, Any]]:
    """TMC/live enriched rows for pump desk + hydrate; registry fallback when feeds timeout."""
    from internal.subnet_names import enrich_subnet_rows

    rows, _src = get_council_subnet_feed(timeout=timeout)
    if rows:
        return rows
    return enrich_subnet_rows(registry_subnet_rows())


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
