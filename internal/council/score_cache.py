"""Shared TTL cache for council hour/day scoring across API handlers."""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

TTL_SEC = int(os.environ.get("SCORE_CACHE_TTL", "60"))

_store: Dict[str, Any] = {"key": None, "ts": 0.0, "hour": [], "day": []}


def _universe_key(subnets: List[Dict[str, Any]], market_context: Optional[Dict[str, Any]]) -> str:
    netuids = sorted(int(s.get("netuid", s.get("id", 0)) or 0) for s in subnets)
    ctx = market_context or {}
    weights = ctx.get("weights") if isinstance(ctx.get("weights"), dict) else {}
    w_bits = tuple(sorted((k, round(float(v or 0), 4)) for k, v in weights.items()))
    payload = {
        "netuids": netuids,
        "tao": round(float(ctx.get("tao_change_24h", 0) or 0), 4),
        "weights": w_bits,
    }
    return hashlib.md5(
        json.dumps(payload, sort_keys=True).encode(),
        usedforsecurity=False,
    ).hexdigest()


def universe_cache_key(
    subnets: List[Dict[str, Any]], market_context: Optional[Dict[str, Any]]
) -> str:
    """Public cache key for subnet universe + market context (hour/day pick caches)."""
    return _universe_key(subnets, market_context)


def score_universe(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]],
    *,
    score_hour,
    score_day,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Score subnets once per TTL; return (hour_scored, day_scored) item lists."""
    ctx = dict(market_context or {})
    # Hoist soul_map-backed dials once — scoring used to re-deepcopy soul_map
    # per subnet via load_impact_strength / load_signal_weights.
    if "impact_strength" not in ctx:
        try:
            from internal.council.weights import load_impact_strength

            ctx["impact_strength"] = float(load_impact_strength())
        except Exception:
            ctx["impact_strength"] = 1.0
    if "signal_weights" not in ctx:
        try:
            from internal.council.weights import load_signal_weights

            ctx["signal_weights"] = load_signal_weights()
        except Exception:
            pass

    key = _universe_key(subnets, ctx)
    now = time.time()
    if _store["key"] == key and now - float(_store["ts"]) < TTL_SEC:
        return _store["hour"], _store["day"]

    hour_scored: List[Dict[str, Any]] = []
    day_scored: List[Dict[str, Any]] = []
    for sn in subnets:
        try:
            hour_scored.append({"subnet": sn, "score": score_hour(sn, ctx)})
            day_scored.append({"subnet": sn, "score": score_day(sn, ctx)})
        except Exception:
            continue

    _store.update(key=key, ts=now, hour=hour_scored, day=day_scored)
    return hour_scored, day_scored


def clear_score_cache() -> None:
    """Test helper — drop cached scores."""
    _store.update(key=None, ts=0.0, hour=[], day=[])
