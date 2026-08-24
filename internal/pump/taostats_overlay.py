"""Overlay TaoStats pool metrics onto subnet rows for pump desk / ladder.

Prod already has TAOSTATS_API_KEY; pump scan historically used bare TMC rows
so buy/sell/fear_greed never reached the classifier. Prefer merged feed, then
warm TaoStats for active ladder netuids (rate-limited).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

_TS_FIELDS = (
    "fear_and_greed",
    "seven_day_prices",
    "price_change_1h",
    "price_change_1d",
    "price_change_7d",
    "price_change_30d",
    "root_prop",
    "liquidity",
    "buys_24hr",
    "sells_24hr",
    "buy_volume_24h",
    "sell_volume_24h",
)


def _f(raw: Any, default: float = 0.0) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _rows_lack_pump_flow_fields(rows: List[Dict[str, Any]]) -> bool:
    """True when most rows lack buy/sell flow and 24h change (pump classifier needs these)."""
    sample = [r for r in rows if isinstance(r, dict) and r.get("netuid") is not None][:30]
    if not sample:
        return True
    lacking = 0
    for row in sample:
        flow = _f(row.get("buy_volume_24h")) + _f(row.get("sell_volume_24h"))
        vol = _f(row.get("volume"))
        chg = row.get("price_change_24h")
        if flow <= 0 and vol <= 0 and chg in (None, "", 0, 0.0):
            lacking += 1
    return lacking >= max(1, (len(sample) + 1) // 2)


def _overlay_tmc_market_fields(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    try:
        from fetchers.taomarketcap import _get_all_subnets_tao, _overlay_market_fields

        tmc = _get_all_subnets_tao()
        if tmc:
            return _overlay_market_fields(subnets, tmc)
    except Exception as exc:
        logger.debug("TMC overlay for pump signals failed: %s", exc)
    return subnets


def active_ladder_netuids(path: Optional[str] = None) -> List[int]:
    """Non-dormant ladder netuids — highest priority for TaoStats rotation."""
    try:
        from internal.pump.state import load_state

        data = load_state(path)
    except Exception:
        return []
    out: List[int] = []
    for entry in (data.get("subnets") or {}).values():
        if not isinstance(entry, dict):
            continue
        phase = str(entry.get("phase") or "DORMANT").upper()
        if phase in {"DORMANT", ""}:
            continue
        try:
            out.append(int(entry.get("netuid")))
        except (TypeError, ValueError):
            continue
    return out


def warm_taostats_metrics(
    netuids: Sequence[int],
    *,
    priority: Optional[Sequence[int]] = None,
    limit: Optional[int] = None,
) -> Dict[int, Dict[str, Any]]:
    """Fetch/cache TaoStats metrics; priority netuids first within rate limit."""
    try:
        from fetchers.taostats_client import (
            get_cached_metrics,
            get_subnet_metrics,
            is_available,
        )
    except Exception as exc:
        logger.debug("taostats import failed: %s", exc)
        return {}

    if not is_available():
        return {}

    cap = limit
    if cap is None:
        try:
            cap = int(os.environ.get("TAOSTATS_PUMP_WARM_LIMIT", "24"))
        except ValueError:
            cap = 24
    cap = max(1, min(int(cap), 40))

    ordered: List[int] = []
    seen = set()
    for nu in list(priority or []) + list(netuids):
        try:
            n = int(nu)
        except (TypeError, ValueError):
            continue
        if n in seen or n < 1:
            continue
        seen.add(n)
        ordered.append(n)

    out: Dict[int, Dict[str, Any]] = {}
    live_fetches = 0
    try:
        live_cap = int(os.environ.get("TAOSTATS_PUMP_LIVE_FETCH_CAP", "5"))
    except ValueError:
        live_cap = 5
    live_cap = max(0, min(live_cap, 5))  # free tier ~5/min — never burst past

    for nu in ordered[:cap]:
        cached = get_cached_metrics(nu)
        if cached:
            out[nu] = cached
            continue
        if live_fetches >= live_cap:
            continue
        metrics = get_subnet_metrics(nu)
        live_fetches += 1
        if metrics:
            out[nu] = metrics
    return out


def apply_taostats_overlay(
    subnet: Dict[str, Any],
    metrics: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Copy TaoStats fields onto a subnet row when missing or zero on the row."""
    if not isinstance(subnet, dict):
        return {}
    out = dict(subnet)
    if not isinstance(metrics, dict):
        return out

    for key in _TS_FIELDS:
        val = metrics.get(key)
        if val is None or val == "" or val == []:
            continue
        existing = out.get(key)
        if existing in (None, "", 0, 0.0, []):
            out[key] = val

    # Prefer TS buy/sell volumes when present (fixes 0.5 placeholder buy_ratio).
    buy = metrics.get("buy_volume_24h")
    sell = metrics.get("sell_volume_24h")
    if buy is not None and _f(buy) > 0:
        out["buy_volume_24h"] = _f(buy)
    if sell is not None and _f(sell) >= 0:
        out["sell_volume_24h"] = _f(sell)

    # Map 1d change onto price_change_24h when TMC gap.
    if metrics.get("price_change_1d") is not None and not out.get("price_change_24h"):
        out["price_change_24h"] = _f(metrics.get("price_change_1d"))
    if metrics.get("price_change_1h") is not None:
        out["price_change_1h"] = _f(metrics.get("price_change_1h"))

    sources = list(out.get("sources") or [])
    if "taostats" not in sources:
        sources.append("taostats")
    out["sources"] = sources
    out["taostats_wired"] = True
    return out


def _union_pump_feed_netuids(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Union committed registry + ladder keys missing from merged/TMC clip."""
    seen: set[int] = set()
    out = list(subnets)
    for row in subnets:
        if not isinstance(row, dict):
            continue
        try:
            seen.add(int(row.get("netuid")))
        except (TypeError, ValueError):
            continue

    added = 0
    try:
        from internal.live_subnets import _netuid_of, _registry_list

        for rec in _registry_list():
            if not isinstance(rec, dict):
                continue
            n = _netuid_of(rec)
            if n is None or n in seen:
                continue
            seen.add(n)
            stub: Dict[str, Any] = {"netuid": n}
            name = rec.get("name")
            if name:
                stub["name"] = name
            stub["sources"] = ["registry"]
            out.append(stub)
            added += 1
    except Exception as exc:
        logger.debug("registry union for pump feed failed: %s", exc)

    try:
        from internal.pump.state import load_state

        ladder = load_state().get("subnets") or {}
        for key, entry in ladder.items():
            if not isinstance(entry, dict):
                continue
            try:
                n = int(entry.get("netuid", key))
            except (TypeError, ValueError):
                continue
            if n in seen:
                continue
            seen.add(n)
            stub = {"netuid": n}
            name = entry.get("name")
            if name:
                stub["name"] = name
            stub["sources"] = ["ladder_state"]
            out.append(stub)
            added += 1
    except Exception as exc:
        logger.debug("ladder union for pump feed failed: %s", exc)

    if added:
        logger.info(
            "pump signals: unioned %d registry/ladder netuids into feed (had %d)",
            added,
            len(subnets),
        )
    return out


def load_subnets_for_pump_signals() -> List[Dict[str, Any]]:
    """Merged feed when cached, else fast TMC — then optional merge warm, TaoStats overlay."""
    subnets: List[Dict[str, Any]] = []
    try:
        from fetchers.merged_data import _get_cached, get_merged_subnet_data

        cached = _get_cached("all_merged")
        if isinstance(cached, dict):
            subnets = list(cached.get("subnets") or [])
        # ponytail: cold worker boot — TMC before blocking merge (90s scan timeout wedge).
        if not subnets:
            try:
                from fetchers.taomarketcap import get_all_subnets

                subnets = list(get_all_subnets() or [])
            except Exception as exc:
                logger.debug("TMC fast path for pump failed: %s", exc)
        if not subnets:
            subnets = list(get_merged_subnet_data() or [])
    except Exception as exc:
        logger.debug("merged feed unavailable for pump: %s", exc)

    if not subnets:
        try:
            from fetchers.taomarketcap import get_all_subnets

            subnets = list(get_all_subnets() or [])
        except Exception as exc:
            logger.warning("TMC feed unavailable for pump: %s", exc)
            return []

    subnets = _union_pump_feed_netuids(subnets)

    if _rows_lack_pump_flow_fields(subnets):
        subnets = _overlay_tmc_market_fields(subnets)
        logger.info(
            "pump signals: overlaid TaoMarketCap market fields (flow/change were missing on feed)"
        )

    netuids = []
    for row in subnets:
        try:
            netuids.append(int(row.get("netuid")))
        except (TypeError, ValueError):
            continue

    priority = active_ladder_netuids()
    # Also prioritize high-volume TMC rows so rotation isn't only dormant.
    by_vol = sorted(
        (r for r in subnets if isinstance(r, dict)),
        key=lambda r: _f(r.get("volume")),
        reverse=True,
    )
    for row in by_vol[:15]:
        try:
            priority.append(int(row.get("netuid")))
        except (TypeError, ValueError):
            continue

    warmed = warm_taostats_metrics(netuids, priority=priority)
    if not warmed:
        return subnets

    out: List[Dict[str, Any]] = []
    for row in subnets:
        try:
            nu = int(row.get("netuid"))
        except (TypeError, ValueError):
            out.append(row)
            continue
        out.append(apply_taostats_overlay(row, warmed.get(nu)))
    return out
