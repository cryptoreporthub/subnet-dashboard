"""Shared subnet feed for council picks and judge scoring (§30-10)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


def get_council_subnet_feed() -> Tuple[List[Dict[str, Any]], str]:
    """Return enriched subnets + source label for pick and judge paths."""
    try:
        from fetchers.taomarketcap import get_all_subnets
        from internal.subnet_names import enrich_subnet_rows

        live = enrich_subnet_rows(get_all_subnets() or [])
        if live:
            return live, "taomarketcap"
    except Exception as exc:
        logger.debug("TMC feed unavailable: %s", exc)

    try:
        from fetchers.merged_data import get_merged_subnet_data
        from internal.subnet_names import enrich_subnet_rows

        merged = get_merged_subnet_data()
        if merged:
            rows = enrich_subnet_rows(merged)
            if rows:
                return rows, "merged"
    except Exception as exc:
        logger.warning("merged feed unavailable: %s", exc)

    return [], "none"


def load_pick_subnets() -> List[Dict[str, Any]]:
    """Subnet rows for daily pick / story paths (§29-7)."""
    rows, _source = get_council_subnet_feed()
    return rows
