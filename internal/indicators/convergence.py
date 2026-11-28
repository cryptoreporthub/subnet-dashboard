"""Shared indicators-convergence payload for API and server-rendered cockpit."""

from __future__ import annotations

from typing import Any, Dict, List

from internal.council.state_vector import (
    _compute_technical_indicators,
    _detect_overbought_convergence,
    _detect_oversold_convergence,
    _get_price_history,
)


def _spark_closes_from_hist(hist: Dict[str, Any]) -> List[float]:
    sparks = hist.get("closes") or []
    if hist.get("source") in ("synthetic", "unavailable") or len(sparks) < 2:
        return []
    return [float(c) for c in sparks[-24:]]


def build_indicators_convergence(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build the canonical convergence contract for top subnets."""
    ranked = sorted(
        subnets,
        key=lambda s: (s.get("emission", 0), s.get("apy", 0), s.get("volume", 0)),
        reverse=True,
    )
    rows: List[Dict[str, Any]] = []
    for sn in ranked[:6]:
        hist = _get_price_history(sn.get("netuid"), sn)
        indicators = _compute_technical_indicators(sn, price_history=hist)
        degraded = bool(indicators.get("degraded"))
        row: Dict[str, Any] = {
            "netuid": sn.get("netuid"),
            "name": sn.get("name"),
            "degraded": degraded,
            "spark_closes": _spark_closes_from_hist(hist),
        }
        if degraded:
            row["reason"] = indicators.get("history_source", "no_ohlcv")
            row["oversold"] = {"convergent": False, "count": 0, "reason": "no_ohlcv"}
            row["overbought"] = {"convergent": False, "count": 0, "reason": "no_ohlcv"}
        else:
            row["oversold"] = _detect_oversold_convergence(indicators)
            row["overbought"] = _detect_overbought_convergence(indicators)
        rows.append(row)
    has_real = any(not r.get("degraded") for r in rows)
    return {
        "data_available": has_real,
        "source": "state_vector" if has_real else "none",
        "reason": None if has_real else "no_ohlcv",
        "subnets": rows,
    }


def indicators_convergence_error_payload(exc: Exception) -> Dict[str, Any]:
    """Honest-depth API error shell (same top-level keys as the happy path)."""
    return {
        "subnets": [],
        "error": str(exc),
        "data_available": False,
        "source": "none",
        "reason": "error",
    }