"""FastAPI routes for the Ruggers Watchlist."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, Field

from internal.ruggers.scanner import scan_subnet_delegations, scan_watchlist_netuids
from internal.ruggers.watchlist import RuggerWatchlist

ruggers_router = APIRouter(tags=["ruggers"])

_watchlist: Optional[RuggerWatchlist] = None


def _get_watchlist() -> RuggerWatchlist:
    global _watchlist
    if _watchlist is None:
        _watchlist = RuggerWatchlist()
    return _watchlist


class RuggerEventIn(BaseModel):
    wallet: str
    netuid: int
    side: str = Field(description="buy or sell (stake/unstake accepted)")
    amount_tao: float
    timestamp: Optional[str] = None
    source: str = "api"
    tx_hash: Optional[str] = None
    subnet_name: Optional[str] = None


@ruggers_router.get("/api/ruggers/summary")
async def ruggers_summary():
    return _get_watchlist().summary()


@ruggers_router.get("/api/ruggers/watchlist")
async def ruggers_watchlist(limit: int = Query(50, ge=1, le=500)):
    items = _get_watchlist().get_watchlist(limit=limit)
    return {"status": "success", "count": len(items), "watchlist": items}


@ruggers_router.get("/api/ruggers/watchlist/{wallet}")
async def ruggers_wallet_profile(wallet: str):
    profile = _get_watchlist().get_profile(wallet)
    if not profile:
        return {"status": "not_found", "wallet": wallet}
    return {"status": "success", "profile": profile}


@ruggers_router.get("/api/ruggers/alerts")
async def ruggers_alerts():
    alerts = _get_watchlist().get_active_alerts()
    return {"status": "success", "count": len(alerts), "alerts": alerts}


@ruggers_router.get("/api/ruggers/subnet/{netuid}")
async def ruggers_subnet_risk(netuid: int):
    return {"status": "success", **_get_watchlist().get_subnet_risk(netuid)}


@ruggers_router.post("/api/ruggers/events")
async def ruggers_record_event(event: RuggerEventIn):
    result = _get_watchlist().record_event(
        wallet=event.wallet,
        netuid=event.netuid,
        side=event.side,
        amount_tao=event.amount_tao,
        timestamp=event.timestamp,
        source=event.source,
        tx_hash=event.tx_hash,
        subnet_name=event.subnet_name,
    )
    return result


@ruggers_router.post("/api/ruggers/scan")
async def ruggers_scan(
    netuids: Optional[List[int]] = Body(default=None),
    top_n: int = Body(default=20),
):
    """Scan TaoStats delegations for wallet flip patterns."""
    if not netuids:
        try:
            from fetchers.taomarketcap import get_all_subnets

            subnets = get_all_subnets() or []
            ranked = sorted(
                subnets,
                key=lambda s: float(s.get("price_change_24h", 0) or 0),
                reverse=True,
            )
            netuids = [
                int(s.get("netuid", s.get("id", 0)))
                for s in ranked[:top_n]
                if s.get("netuid", s.get("id")) is not None
            ]
        except Exception:
            netuids = list(range(1, min(top_n + 1, 30)))

    names = {}
    try:
        from fetchers.taomarketcap import get_all_subnets

        for s in get_all_subnets() or []:
            nuid = s.get("netuid", s.get("id"))
            if nuid is not None:
                names[int(nuid)] = s.get("name")
    except Exception:
        pass

    return scan_watchlist_netuids(netuids, subnet_names=names, watchlist=_get_watchlist())
