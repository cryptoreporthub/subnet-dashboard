"""Horizon-end price lookup from price_cache candles (Phase J1)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

PRICE_CACHE_PATH = os.path.join("data", "price_cache.json")
CANDLE_LOOKUP_MINUTES = 15
MIN_CANDLES_FOR_GRADE = 3


def _load_cache(path: str = PRICE_CACHE_PATH) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        text = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _candles_for_netuid(cache: Dict[str, Any], netuid: Any) -> List[Dict[str, Any]]:
    key = str(netuid)
    block = cache.get(key)
    if not isinstance(block, dict):
        block = cache.get(netuid)
    if not isinstance(block, dict):
        return []
    candles = block.get("candles") or []
    return [c for c in candles if isinstance(c, dict)]


def _window_candles(
    candles: List[Dict[str, Any]],
    resolve_at: datetime,
    window_minutes: int = CANDLE_LOOKUP_MINUTES,
) -> List[Dict[str, Any]]:
    delta_sec = window_minutes * 60
    out: List[Dict[str, Any]] = []
    target = resolve_at.timestamp()
    for candle in candles:
        ts = _parse_ts(candle.get("timestamp"))
        if ts is None:
            continue
        if abs(ts.timestamp() - target) <= delta_sec:
            out.append(candle)
    return out


def _median_price(candles: List[Dict[str, Any]]) -> float:
    closes = []
    for c in candles:
        try:
            close = float(c.get("close", 0) or 0)
            if close > 0:
                closes.append(close)
        except (TypeError, ValueError):
            continue
    if not closes:
        return 0.0
    closes.sort()
    mid = len(closes) // 2
    if len(closes) % 2:
        return closes[mid]
    return (closes[mid - 1] + closes[mid]) / 2


def _vwap_price(candles: List[Dict[str, Any]]) -> float:
    num = 0.0
    den = 0.0
    for c in candles:
        try:
            close = float(c.get("close", 0) or 0)
            vol = float(c.get("volume", 0) or 0)
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        weight = vol if vol > 0 else 1.0
        num += close * weight
        den += weight
    if den <= 0:
        return _median_price(candles)
    return num / den


def price_at_resolve_at(
    netuid: Any,
    resolve_at: datetime,
    *,
    cache: Optional[Dict[str, Any]] = None,
    cache_path: str = PRICE_CACHE_PATH,
) -> Tuple[str, float, Dict[str, Any]]:
    """Return (status, price, meta). status: ok | ungradeable."""
    cache = cache if cache is not None else _load_cache(cache_path)
    candles = _candles_for_netuid(cache, netuid)
    window = _window_candles(candles, resolve_at)
    meta: Dict[str, Any] = {
        "price_source": None,
        "price_lag_seconds": None,
        "candles_in_window": len(window),
    }

    if len(window) < MIN_CANDLES_FOR_GRADE:
        return "ungradeable", 0.0, meta

    total_volume = sum(float(c.get("volume", 0) or 0) for c in window)
    if total_volume <= 0:
        # ponytail: thin subnets often lack candle volume — median close still grades price
        price = _median_price(window)
        if price <= 0:
            return "ungradeable", 0.0, meta
        meta["price_source"] = "median_no_volume"
        nearest = min(
            (c for c in window if _parse_ts(c.get("timestamp"))),
            key=lambda c: abs(_parse_ts(c.get("timestamp")).timestamp() - resolve_at.timestamp()),  # type: ignore
            default=None,
        )
        if nearest:
            ts = _parse_ts(nearest.get("timestamp"))
            if ts:
                meta["price_lag_seconds"] = int(abs(ts.timestamp() - resolve_at.timestamp()))
        return "ok", float(price), meta

    price = _vwap_price(window)
    if price <= 0:
        price = _median_price(window)
        meta["price_source"] = "median"
    else:
        meta["price_source"] = "vwap"

    nearest = min(
        (c for c in window if _parse_ts(c.get("timestamp"))),
        key=lambda c: abs(_parse_ts(c.get("timestamp")).timestamp() - resolve_at.timestamp()),  # type: ignore
        default=None,
    )
    if nearest:
        ts = _parse_ts(nearest.get("timestamp"))
        if ts:
            meta["price_lag_seconds"] = int(abs(ts.timestamp() - resolve_at.timestamp()))

    return "ok", float(price), meta
