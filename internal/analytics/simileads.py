"""SimiLeads — score rising while price stays flat (mispricing watch)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _f(val: Any, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _price_by_netuid(subnets: List[Dict[str, Any]]) -> Dict[int, float]:
    out: Dict[int, float] = {}
    for sn in subnets or []:
        if not isinstance(sn, dict):
            continue
        nu = sn.get("netuid", sn.get("id"))
        try:
            netuid = int(nu)
        except (TypeError, ValueError):
            continue
        out[netuid] = _f(sn.get("price_change_24h"))
    return out


def build_simileads_rows(
    subnets: List[Dict[str, Any]],
    simivision_top: List[Dict[str, Any]],
    *,
    limit: int = 3,
    score_delta_min: float = 3.0,
    price_flat_max: float = 2.0,
) -> List[Dict[str, Any]]:
    """Return ranked SimiLeads rows when council warms ahead of tape."""
    prices = _price_by_netuid(subnets if isinstance(subnets, list) else [])
    rows: List[Dict[str, Any]] = []
    for pick in simivision_top or []:
        if not isinstance(pick, dict):
            continue
        nu = pick.get("netuid")
        try:
            netuid = int(nu)
        except (TypeError, ValueError):
            continue
        score_delta = _f(pick.get("conviction_delta"))
        if score_delta <= 0:
            score_delta = _f(pick.get("delta_value"))
        if score_delta <= 0:
            continue
        price_delta = prices.get(netuid, 0.0)
        if abs(price_delta) > price_flat_max:
            continue
        if score_delta < score_delta_min:
            continue
        lag_index = round(score_delta - abs(price_delta), 1)
        rows.append(
            {
                "netuid": netuid,
                "name": pick.get("name") or f"SN{netuid}",
                "score_delta": round(score_delta, 1),
                "price_delta": round(price_delta, 2),
                "lag_index": lag_index,
            }
        )
    rows.sort(key=lambda r: (-float(r["lag_index"]), -float(r["score_delta"])))
    return rows[: max(0, int(limit))]
