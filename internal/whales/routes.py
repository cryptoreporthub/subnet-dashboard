"""FastAPI routes for the Whale Intelligence service."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from internal.whales.scanner import scan_netuids, scan_subnet_delegations
from internal.whales.service import TRACKING_DIMENSIONS, WhaleIntelligenceService

whales_router = APIRouter(tags=["whales"])

_service: Optional[WhaleIntelligenceService] = None


def _get_service() -> WhaleIntelligenceService:
    global _service
    if _service is None:
        _service = WhaleIntelligenceService()
    return _service


class WhaleEventIn(BaseModel):
    wallet: str
    netuid: int
    side: str = Field(description="buy or sell")
    amount_tao: float
    timestamp: Optional[str] = None
    source: str = "api"
    tx_hash: Optional[str] = None
    subnet_name: Optional[str] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    market_cap_rank: Optional[int] = None
    total_stake_tao: Optional[float] = None
    price_change_after_hours: Optional[float] = None


@whales_router.get("/api/whales/summary")
async def whales_summary():
    return _get_service().summary()


@whales_router.get("/api/whales/dimensions")
async def whales_dimensions():
    return {
        "status": "success",
        "dimensions": [
            {
                "id": "ruggers",
                "label": "Ruggers",
                "description": "Fast flippers — avoid following, exit before their median hold time",
            },
            {
                "id": "alpha_whales",
                "label": "Alpha Whales",
                "description": "Highest win-rate and return % on closed trades",
            },
            {
                "id": "market_movers",
                "label": "Market Movers",
                "description": "Whales whose entries move small/mid-cap subnet prices the most",
            },
            {
                "id": "early_movers",
                "label": "Early Movers",
                "description": "Enter subnets before major price moves (leading indicator)",
            },
            {
                "id": "conviction_holders",
                "label": "Conviction Holders",
                "description": "Long-hold smart money with positive track records",
            },
            {
                "id": "rotators",
                "label": "Rotators",
                "description": "Systematic cross-subnet capital rotation patterns",
            },
        ],
    }


@whales_router.get("/api/whales/leaderboards")
async def whales_all_leaderboards(limit: int = Query(25, ge=1, le=200)):
    boards = _get_service().get_all_leaderboards(limit=limit)
    return {"status": "success", "leaderboards": boards}


@whales_router.get("/api/whales/leaderboards/{category}")
async def whales_leaderboard(category: str, limit: int = Query(25, ge=1, le=200)):
    if category not in TRACKING_DIMENSIONS:
        raise HTTPException(404, f"Unknown category. Choose from: {TRACKING_DIMENSIONS}")
    items = _get_service().get_leaderboard(category, limit=limit)
    return {"status": "success", "category": category, "count": len(items), "leaderboard": items}


@whales_router.get("/api/whales/wallet/{wallet}")
async def whales_wallet(wallet: str):
    profile = _get_service().get_profile(wallet)
    if not profile:
        return {"status": "not_found", "wallet": wallet}
    return {"status": "success", "profile": profile}


@whales_router.get("/api/whales/alerts")
async def whales_alerts():
    alerts = _get_service().get_active_alerts()
    return {"status": "success", **alerts}


@whales_router.get("/api/whales/subnet/{netuid}/flow")
async def whales_subnet_flow(netuid: int):
    return {"status": "success", **_get_service().get_subnet_flow(netuid)}


@whales_router.post("/api/whales/events")
async def whales_record_event(event: WhaleEventIn):
    return _get_service().record_event(
        wallet=event.wallet,
        netuid=event.netuid,
        side=event.side,
        amount_tao=event.amount_tao,
        timestamp=event.timestamp,
        source=event.source,
        tx_hash=event.tx_hash,
        subnet_name=event.subnet_name,
        entry_price=event.entry_price,
        exit_price=event.exit_price,
        market_cap_rank=event.market_cap_rank,
        total_stake_tao=event.total_stake_tao,
        price_change_after_hours=event.price_change_after_hours,
    )


@whales_router.post("/api/whales/scan")
async def whales_scan(
    netuids: Optional[List[int]] = Body(default=None),
    top_n: int = Body(default=20),
):
    meta_by_id = {}
    if not netuids:
        try:
            from fetchers.taomarketcap import get_all_subnets

            subnets = get_all_subnets() or []
            ranked = sorted(
                subnets,
                key=lambda s: float(s.get("price_change_24h", 0) or 0),
                reverse=True,
            )
            selected = ranked[:top_n]
            netuids = []
            for s in selected:
                nuid = s.get("netuid", s.get("id"))
                if nuid is None:
                    continue
                nuid = int(nuid)
                netuids.append(nuid)
                meta_by_id[nuid] = s
        except Exception:
            netuids = list(range(1, min(top_n + 1, 30)))
    else:
        try:
            from fetchers.taomarketcap import get_all_subnets

            for s in get_all_subnets() or []:
                nuid = s.get("netuid", s.get("id"))
                if nuid is not None:
                    meta_by_id[int(nuid)] = s
        except Exception:
            pass

    return scan_netuids(netuids, subnet_meta_by_id=meta_by_id, service=_get_service())
