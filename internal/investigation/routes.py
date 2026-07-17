"""FastAPI routes for on-chain investigation."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, Field

from internal.investigation.service import (
    build_investigation_report,
    investigate_owner_check,
    investigate_subnet_sellers,
    investigate_wallet,
)

investigation_router = APIRouter(tags=["investigation"])


class InvestigateAskIn(BaseModel):
    question: str = Field(min_length=1)
    netuid: Optional[int] = None
    wallet: Optional[str] = None


@investigation_router.get("/api/investigate/subnet/{netuid}/sellers")
async def api_subnet_sellers(netuid: int, days: int = Query(7, ge=1, le=90), limit: int = Query(50, ge=1, le=200)):
    result = investigate_subnet_sellers(netuid, limit=limit)
    result["days_requested"] = days
    return result


@investigation_router.get("/api/investigate/wallet/{wallet}")
async def api_wallet_activity(wallet: str, days: int = Query(30, ge=1, le=365), limit: int = Query(50, ge=1, le=200)):
    result = investigate_wallet(wallet, limit=limit)
    result["days_requested"] = days
    return result


@investigation_router.get("/api/investigate/subnet/{netuid}/owner-check")
async def api_owner_check(netuid: int, wallets: str = Query("", description="Comma-separated SS58 addresses")):
    parsed: List[str] = [w.strip() for w in wallets.split(",") if w.strip()]
    return investigate_owner_check(netuid, parsed)


@investigation_router.post("/api/investigate/ask")
async def api_investigate_ask(body: InvestigateAskIn):
    return build_investigation_report(body.question, netuid=body.netuid, wallet=body.wallet)
