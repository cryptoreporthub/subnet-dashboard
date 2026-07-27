"""Scoring universe cap — represent top names, hunt low/mid cap.

Legacy cap sorted by volume + market_cap, so mega subnets (Chutes, Targon, …)
filled every slot. This module keeps a small ``majors`` budget then fills the
rest from a mid-cap focus band (marketcap_rank 16–70 by default).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from internal.subnets.tradable import subnet_netuid, subnet_volume


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def marketcap_rank(sn: Dict[str, Any]) -> int:
    raw = sn.get("marketcap_rank")
    try:
        r = int(raw)
        return r if r > 0 else 10_000
    except (TypeError, ValueError):
        return 10_000


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


def _focus_tier(
    sn: Dict[str, Any],
    *,
    mid_min: int,
    mid_max: int,
    majors_top_rank: int,
) -> int:
    """Higher = prefer for remaining slots after the majors budget."""
    r = marketcap_rank(sn)
    if mid_min <= r <= mid_max:
        return 3  # mid-cap focus band
    if r > mid_max:
        return 2  # low cap / unranked gems
    if r <= majors_top_rank:
        return 1  # large-cap spillover (did not win a major slot)
    return 2


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

    majors_top_rank = _env_int("SCORING_CAP_MAJORS_TOP_RANK", 15)
    majors_max_cfg = _env_int("SCORING_CAP_MAJORS_MAX", 8)
    mid_min = _env_int("SCORING_CAP_MID_RANK_MIN", 16)
    mid_max = _env_int("SCORING_CAP_MID_RANK_MAX", 70)

    # Reserve the majority of slots for mid/low focus; majors stay visible but bounded.
    focus_floor = 0 if cap <= 1 else max(1, cap // 2)
    majors_max = min(majors_max_cfg, max(0, cap - focus_floor))

    majors_pool = [sn for sn in subnets if marketcap_rank(sn) <= majors_top_rank]
    majors_pool.sort(key=activity_rank_key, reverse=True)
    majors = majors_pool[:majors_max]
    major_uids = {u for sn in majors if (u := subnet_netuid(sn)) is not None}

    rest = [sn for sn in subnets if subnet_netuid(sn) not in major_uids]
    rest.sort(
        key=lambda sn: (
            _focus_tier(
                sn,
                mid_min=mid_min,
                mid_max=mid_max,
                majors_top_rank=majors_top_rank,
            ),
            activity_rank_key(sn),
        ),
        reverse=True,
    )
    remaining = max(0, cap - len(majors))
    return majors + rest[:remaining]
