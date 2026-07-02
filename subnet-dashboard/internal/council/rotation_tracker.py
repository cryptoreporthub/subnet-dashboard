"""
Rotation tracker backend for the Council engine.

Detects subnet rotation patterns and clusters subnets by volatility. Output is
deterministic and includes a confidence score for each detected pattern so the
front end can rank or filter signals without extra processing.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from internal.council.state_vector import score_subnet_for_day


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except Exception:
        return default


def _volatility_proxy(subnet: Dict[str, Any]) -> float:
    """Proxy volatility using absolute 24h change and 7d dispersion."""
    chg24 = abs(_safe_float(subnet.get("price_change_24h")))
    chg7 = abs(_safe_float(subnet.get("price_change_7d")))
    return round(max(chg24, chg7 / 7), 3)


def _momentum_score(subnet: Dict[str, Any]) -> float:
    """Combine day score (Phase 1) with 24h price change for ranking."""
    try:
        day_score = score_subnet_for_day(subnet, {}).get("total_score", 0.0)
    except Exception:
        day_score = 50.0
    chg24 = _safe_float(subnet.get("price_change_24h"))
    return round(day_score * 0.7 + max(-10, min(10, chg24)) * 1.5, 3)


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * pct
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def cluster_by_volatility(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Split subnets into high / low / core volatility clusters."""
    if not subnets:
        return {
            "high": [],
            "low": [],
            "core": [],
            "summary": {"mean_volatility": 0.0, "count": 0},
        }

    scored = [
        {
            "netuid": sn.get("netuid"),
            "name": sn.get("name"),
            "volatility": _volatility_proxy(sn),
            "price_change_24h": _safe_float(sn.get("price_change_24h")),
        }
        for sn in subnets
        if sn.get("netuid") is not None
    ]

    vols = [s["volatility"] for s in scored]
    high_threshold = _percentile(vols, 0.75)
    low_threshold = _percentile(vols, 0.25)

    high = [s for s in scored if s["volatility"] >= high_threshold]
    low = [s for s in scored if s["volatility"] <= low_threshold]
    core = [s for s in scored if low_threshold < s["volatility"] < high_threshold]

    return {
        "high": high,
        "low": low,
        "core": core,
        "summary": {
            "count": len(scored),
            "mean_volatility": round(statistics.mean(vols), 3) if vols else 0.0,
            "high_threshold": high_threshold,
            "low_threshold": low_threshold,
        },
    }


def detect_rotation_patterns(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return rotation patterns with confidence scores.

    Confidence is derived from the share of qualifying subnets relative to the
    total sample, capped at 1.0.
    """
    if not subnets:
        return []

    n = len(subnets)
    price_changes = [_safe_float(sn.get("price_change_24h")) for sn in subnets]
    volumes = [_safe_float(sn.get("volume")) for sn in subnets]
    apys = [_safe_float(sn.get("apy")) for sn in subnets]
    emissions = [_safe_float(sn.get("emission")) for sn in subnets]

    median_price_change = _percentile(price_changes, 0.5)
    median_volume = _percentile(volumes, 0.5)
    median_apy = _percentile(apys, 0.5)
    median_emission = _percentile(emissions, 0.5)

    patterns: List[Dict[str, Any]] = []

    # Momentum rotation: strong 24h move + above-median volume.
    momentum_candidates = [
        sn
        for sn in subnets
        if _safe_float(sn.get("price_change_24h")) > 3
        and _safe_float(sn.get("volume")) >= median_volume
    ]
    if momentum_candidates:
        confidence = min(1.0, len(momentum_candidates) / max(1, n * 0.4))
        patterns.append({
            "pattern": "momentum_rotation",
            "description": "Subnets with strong 24h momentum and healthy volume",
            "netuids": [sn.get("netuid") for sn in momentum_candidates],
            "count": len(momentum_candidates),
            "confidence": round(confidence, 3),
        })

    # Yield rotation: above-median APY and positive 24h change.
    yield_candidates = [
        sn
        for sn in subnets
        if _safe_float(sn.get("apy")) >= median_apy
        and _safe_float(sn.get("price_change_24h")) > 0
    ]
    if yield_candidates:
        confidence = min(1.0, len(yield_candidates) / max(1, n * 0.4))
        patterns.append({
            "pattern": "yield_rotation",
            "description": "High-yield subnets attracting rotation",
            "netuids": [sn.get("netuid") for sn in yield_candidates],
            "count": len(yield_candidates),
            "confidence": round(confidence, 3),
        })

    # Emission defense: high emission + negative 24h change (flight to safety).
    defense_candidates = [
        sn
        for sn in subnets
        if _safe_float(sn.get("emission")) >= median_emission
        and _safe_float(sn.get("price_change_24h")) < -1
    ]
    if defense_candidates:
        confidence = min(1.0, len(defense_candidates) / max(1, n * 0.4))
        patterns.append({
            "pattern": "emission_defense",
            "description": "High Daily Rewards subnets used as defensive rotation",
            "netuids": [sn.get("netuid") for sn in defense_candidates],
            "count": len(defense_candidates),
            "confidence": round(confidence, 3),
        })

    # Mean-reversion rotation: oversold bounce setup (negative 24h + high yield).
    reversion_candidates = [
        sn
        for sn in subnets
        if _safe_float(sn.get("price_change_24h")) < -3
        and _safe_float(sn.get("apy")) >= median_apy
    ]
    if reversion_candidates:
        confidence = min(1.0, len(reversion_candidates) / max(1, n * 0.4))
        patterns.append({
            "pattern": "mean_reversion_rotation",
            "description": "Oversold high-yield subnets poised for mean reversion",
            "netuids": [sn.get("netuid") for sn in reversion_candidates],
            "count": len(reversion_candidates),
            "confidence": round(confidence, 3),
        })

    return sorted(patterns, key=lambda p: p["confidence"], reverse=True)


def get_rotation_summary(subnets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Return the full rotation summary (patterns + volatility clusters)."""
    subnets = subnets or []
    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "patterns": detect_rotation_patterns(subnets),
        "volatility_clusters": cluster_by_volatility(subnets),
    }
