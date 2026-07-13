"""Anomaly guards — z-score, ROC, volume spike (Phase O)."""

from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional

ZSCORE_THRESHOLD = float(os.environ.get("HUB_ZSCORE_THRESHOLD", "2.0"))
ROC_PCT = float(os.environ.get("HUB_ROC_PCT", "5.0"))
ROC_WINDOW = int(os.environ.get("HUB_ROC_WINDOW", "6"))
VOLUME_SPIKE_RATIO = float(os.environ.get("HUB_VOLUME_SPIKE_RATIO", "2.5"))
MIN_CANDLES = int(os.environ.get("HUB_MIN_CANDLES", "30"))
TAO_BREADTH_PCT = float(os.environ.get("HUB_TAO_BREADTH_PCT", "8.0"))
DUAL_GUARD_Z = float(os.environ.get("HUB_DUAL_GUARD_Z", "2.5"))

TRACKER_IDS = (
    "price_population_z",
    "price_roc",
    "volume_spike",
    "tao_breadth",
    "social_shift",
)


def population_zscore(value: float, population: List[float]) -> float:
    if not population:
        return 0.0
    mean = sum(population) / len(population)
    var = sum((x - mean) ** 2 for x in population) / len(population)
    std = math.sqrt(var) if var > 0 else 0.0
    if std <= 1e-9:
        return 0.0
    return (value - mean) / std


def rate_of_change_pct(closes: List[float], window: int = ROC_WINDOW) -> Optional[float]:
    if len(closes) < window + 1:
        return None
    start = closes[-(window + 1)]
    end = closes[-1]
    if start <= 0:
        return None
    return (end - start) / start * 100.0


def volume_spike_ratio(volumes: List[float]) -> Optional[float]:
    if len(volumes) < MIN_CANDLES:
        return None
    tail = volumes[-MIN_CANDLES:]
    recent = tail[-1]
    baseline = sum(tail[:-1]) / max(len(tail) - 1, 1)
    if baseline <= 0:
        return None
    return recent / baseline


def _candles_for_netuid(cache: Dict[str, Any], netuid: Any) -> Dict[str, List[float]]:
    raw = cache.get(str(netuid)) or cache.get(int(netuid) if str(netuid).isdigit() else netuid)
    if not isinstance(raw, dict):
        return {"closes": [], "volumes": []}
    closes: List[float] = []
    volumes: List[float] = []
    for candle in raw.get("candles") or []:
        if not isinstance(candle, dict):
            continue
        cl = candle.get("close")
        if cl is None:
            continue
        try:
            closes.append(float(cl))
            volumes.append(float(candle.get("volume", 0) or 0))
        except (TypeError, ValueError):
            continue
    return {"closes": closes, "volumes": volumes}


def _direction_from_value(value: float) -> str:
    if value > 0:
        return "bullish"
    if value < 0:
        return "bearish"
    return "neutral"


def evaluate_subnet_anomalies(
    sn: Dict[str, Any],
    *,
    cache: Dict[str, Any],
    population_changes: List[float],
) -> List[Dict[str, Any]]:
    """Return raw anomaly hits for one subnet (may be empty)."""
    netuid = sn.get("netuid") or sn.get("id")
    if netuid is None:
        return []

    try:
        chg24 = float(sn.get("price_change_24h", 0) or 0)
    except (TypeError, ValueError):
        chg24 = 0.0

    hits: List[Dict[str, Any]] = []
    z = population_zscore(chg24, population_changes)
    if abs(z) >= ZSCORE_THRESHOLD:
        hits.append(
            {
                "type": "price_population_z",
                "subnet_id": netuid,
                "name": sn.get("name"),
                "z_score": round(z, 4),
                "price_change_24h": chg24,
                "direction": _direction_from_value(chg24),
                "severity": "warning" if abs(z) < DUAL_GUARD_Z else "critical",
            }
        )

    series = _candles_for_netuid(cache, netuid)
    closes = series["closes"]
    volumes = series["volumes"]

    roc = rate_of_change_pct(closes)
    if roc is not None and abs(roc) >= ROC_PCT and len(closes) >= MIN_CANDLES:
        hits.append(
            {
                "type": "price_roc",
                "subnet_id": netuid,
                "name": sn.get("name"),
                "roc_pct": round(roc, 4),
                "direction": _direction_from_value(roc),
                "severity": "warning",
            }
        )

    vol_ratio = volume_spike_ratio(volumes)
    if vol_ratio is not None and vol_ratio >= VOLUME_SPIKE_RATIO:
        hits.append(
            {
                "type": "volume_spike",
                "subnet_id": netuid,
                "name": sn.get("name"),
                "volume_ratio": round(vol_ratio, 4),
                "direction": "bullish",
                "severity": "info",
            }
        )

    return _filter_dual_guard(hits)


def evaluate_tao_breadth(population_changes: List[float]) -> Optional[Dict[str, Any]]:
    if not population_changes:
        return None
    avg = sum(population_changes) / len(population_changes)
    if abs(avg) < TAO_BREADTH_PCT:
        return None
    return {
        "type": "tao_breadth",
        "subnet_id": None,
        "avg_change_24h": round(avg, 4),
        "direction": _direction_from_value(avg),
        "severity": "warning" if abs(avg) < TAO_BREADTH_PCT * 1.5 else "critical",
    }


def _filter_dual_guard(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Require 2+ hits unless z-score is extreme."""
    if len(hits) <= 1:
        only = hits[0] if hits else None
        if only and only.get("type") == "price_population_z":
            z = abs(float(only.get("z_score", 0) or 0))
            if z >= DUAL_GUARD_Z:
                return hits
        return []
    return hits


def threshold_snapshot() -> Dict[str, Any]:
    return {
        "zscore": ZSCORE_THRESHOLD,
        "dual_guard_z": DUAL_GUARD_Z,
        "roc_pct": ROC_PCT,
        "roc_window": ROC_WINDOW,
        "volume_spike_ratio": VOLUME_SPIKE_RATIO,
        "min_candles": MIN_CANDLES,
        "tao_breadth_pct": TAO_BREADTH_PCT,
    }
