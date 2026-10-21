"""Scoring universe cap — hunt low/mid cap; mega names via snapshot only.

Heuristic cap (no fresh snapshot) excludes top marketcap_rank names (Chutes,
Targon, Lium, Affine, …) so scoring budget goes to the low–mid band.
Council ``score_snapshots.json`` ranking still promotes any netuid when fresh.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from internal.subnets.tradable import subnet_netuid, subnet_volume

_UNRANKED = 10_000


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def marketcap_rank(sn: Dict[str, Any]) -> int:
    raw = sn.get("marketcap_rank")
    try:
        r = int(raw)
        return r if r > 0 else _UNRANKED
    except (TypeError, ValueError):
        return _UNRANKED


def activity_rank_key(sn: Dict[str, Any]) -> Tuple[Any, ...]:
    """Higher sorts first — liquidity / activity within a tier."""
    vol = subnet_volume(sn)
    try:
        mcap = float(sn.get("market_cap", 0) or 0)
    except (TypeError, ValueError):
        mcap = 0.0
    try:
        emission = float(sn.get("emission", 0) or 0)
    except (TypeError, ValueError):
        emission = 0.0
    mcr = sn.get("marketcap_rank")
    try:
        rank_bonus = -int(mcr) if mcr not in (None, "", 0, "0") else 0
    except (TypeError, ValueError):
        rank_bonus = 0
    try:
        priced = 1 if float(sn.get("price") or 0) > 0 else 0
    except (TypeError, ValueError):
        priced = 0
    if vol > 0 or mcap > 0:
        return (priced, 1, vol, mcap, rank_bonus, emission)
    return (priced, 0, 0.0, 0.0, 0, emission)


def _focus_tier(sn: Dict[str, Any], *, mid_min: int, mid_max: int) -> int:
    """Higher = prefer for hunt-pool slots."""
    r = marketcap_rank(sn)
    if mid_min <= r <= mid_max:
        return 3  # mid-cap focus band
    if r > mid_max or r >= _UNRANKED:
        return 2  # low cap / unranked
    return 0


def _heuristic_hunt_pool(
    subnets: List[Dict[str, Any]],
    *,
    mega_ceiling_rank: int,
    mid_min: int,
    mid_max: int,
) -> List[Dict[str, Any]]:
    """Subnets eligible for heuristic cap — mega ranks excluded."""
    pool: List[Dict[str, Any]] = []
    for sn in subnets:
        r = marketcap_rank(sn)
        if r <= mega_ceiling_rank:
            continue
        if mid_min <= r <= mid_max or r > mid_max or r >= _UNRANKED:
            pool.append(sn)
    pool.sort(
        key=lambda sn: (_focus_tier(sn, mid_min=mid_min, mid_max=mid_max), activity_rank_key(sn)),
        reverse=True,
    )
    return pool


def cap_subnets_for_scoring(
    subnets: List[Dict[str, Any]],
    limit: Optional[int] = None,
    *,
    default_limit: int = 40,
) -> List[Dict[str, Any]]:
    """Return up to ``limit`` subnets to score on hot paths / snapshot jobs."""
    cap = limit if limit is not None else default_limit
    if not subnets or len(subnets) <= cap:
        return list(subnets)

    try:
        from internal.council.score_snapshots import rank_subnets_by_snapshot

        ranked = rank_subnets_by_snapshot(subnets, horizon="day")
        if ranked:
            return ranked[:cap]
    except Exception:
        pass

    mega_ceiling = _env_int("SCORING_CAP_MEGA_CEILING_RANK", 10)
    mid_min = _env_int("SCORING_CAP_MID_RANK_MIN", 11)
    mid_max = _env_int("SCORING_CAP_MID_RANK_MAX", 75)

    pool = _heuristic_hunt_pool(
        subnets,
        mega_ceiling_rank=mega_ceiling,
        mid_min=mid_min,
        mid_max=mid_max,
    )
    return pool[:cap]
