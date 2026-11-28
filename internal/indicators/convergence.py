"""Shared indicators-convergence payload for API and server-rendered cockpit."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from internal.council.state_vector import (
    _compute_technical_indicators,
    _detect_overbought_convergence,
    _detect_oversold_convergence,
    _get_price_history,
)

_PUBLIC_ERROR = "indicators_convergence_unavailable"


def _rank_metric(sn: Dict[str, Any], key: str) -> float:
    raw = sn.get(key, 0)
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _spark_closes_from_hist(hist: Optional[Dict[str, Any]], *, degraded: bool) -> List[float]:
    if degraded:
        return []
    if not isinstance(hist, dict):
        return []
    sparks = hist.get("closes") or []
    if hist.get("source") in ("synthetic", "unavailable") or len(sparks) < 2:
        return []
    out: List[float] = []
    for c in sparks[-24:]:
        try:
            out.append(float(c))
        except (TypeError, ValueError):
            continue
    return out


def build_indicators_convergence(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build the canonical convergence contract for top subnets."""
    ranked = sorted(
        subnets,
        key=lambda s: (
            _rank_metric(s, "emission"),
            _rank_metric(s, "apy"),
            _rank_metric(s, "volume"),
        ),
        reverse=True,
    )
    rows: List[Dict[str, Any]] = []
    for sn in ranked[:6]:
        hist = _get_price_history(sn.get("netuid"), sn)
        if not isinstance(hist, dict):
            hist = {}
        indicators = _compute_technical_indicators(sn, price_history=hist)
        degraded = bool(indicators.get("degraded"))
        row: Dict[str, Any] = {
            "netuid": sn.get("netuid"),
            "name": sn.get("name"),
            "degraded": degraded,
            "spark_closes": _spark_closes_from_hist(hist, degraded=degraded),
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
    """Honest-depth error shell (same top-level keys as the happy path; no exc leak)."""
    _ = exc
    return {
        "subnets": [],
        "error": _PUBLIC_ERROR,
        "data_available": False,
        "source": "none",
        "reason": "error",
    }