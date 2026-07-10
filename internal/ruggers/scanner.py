"""Delegate ruggers scanner to Whale Intelligence scanner."""

from __future__ import annotations

from typing import Dict, List, Optional

from internal.ruggers.watchlist import RuggerWatchlist
from internal.whales.scanner import scan_netuids
from internal.whales.scanner import scan_subnet_delegations as _whale_scan_subnet
from internal.whales.service import WhaleIntelligenceService


def scan_subnet_delegations_legacy(
    netuid: int,
    watchlist: Optional[RuggerWatchlist] = None,
    subnet_name: Optional[str] = None,
) -> Dict:
    service = watchlist._service if watchlist else WhaleIntelligenceService()
    meta = {"name": subnet_name} if subnet_name else {}
    return _whale_scan_subnet(netuid, service=service, subnet_meta=meta)


def scan_watchlist_netuids(
    netuids: List[int],
    subnet_names: Optional[Dict[int, str]] = None,
    watchlist: Optional[RuggerWatchlist] = None,
) -> Dict:
    service = (watchlist._service if watchlist else None) or WhaleIntelligenceService()
    meta = {n: {"name": subnet_names[n]} for n in netuids if subnet_names and n in subnet_names}
    return scan_netuids(netuids, subnet_meta_by_id=meta, service=service)


# Backward-compatible alias
scan_subnet_delegations = scan_subnet_delegations_legacy
