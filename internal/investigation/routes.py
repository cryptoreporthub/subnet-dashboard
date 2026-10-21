"""FastAPI routes for on-chain investigation."""

from __future__ import annotations

import re
from typing import List, Optional

from fastapi import APIRouter, Body, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from internal.investigation.service import (
    build_investigation_report,
    investigate_owner_check,
    investigate_subnet_sellers,
    investigate_wallet,
    trace_wallet_flow,
)

investigation_router = APIRouter(tags=["investigation"])

# SS58 addresses are base58 (no 0, O, I, l) and 47-48 characters for the generic Substrate prefix.
# The wallet string is a cache key and an upstream query, so it is validated before either.
SS58_PATTERN = r"^[1-9A-HJ-NP-Za-km-z]{46,49}$"
_SS58 = re.compile(SS58_PATTERN)
MAX_QUESTION_CHARS = 500
MAX_OWNER_CHECK_WALLETS = 20


class InvestigateAskIn(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    netuid: Optional[int] = None
    wallet: Optional[str] = Field(default=None, pattern=SS58_PATTERN)


@investigation_router.get("/api/investigate/subnet/{netuid}/sellers")
async def api_subnet_sellers(netuid: int, days: int = Query(7, ge=1, le=90), limit: int = Query(50, ge=1, le=200)):
    result = investigate_subnet_sellers(netuid, limit=limit)
    result["days_requested"] = days
    return result


@investigation_router.get("/api/investigate/wallet/{wallet}")
async def api_wallet_activity(wallet: str = Path(pattern=SS58_PATTERN), days: int = Query(30, ge=1, le=365), limit: int = Query(50, ge=1, le=200)):
    result = investigate_wallet(wallet, limit=limit)
    result["days_requested"] = days
    return result


@investigation_router.get("/api/investigate/wallet/{wallet}/flow")
async def api_wallet_flow(
    wallet: str = Path(pattern=SS58_PATTERN),
    counterparty: Optional[str] = Query(
        None, pattern=SS58_PATTERN, description="Optional second wallet to trace against"
    ),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
):
    result = trace_wallet_flow(wallet, counterparty=counterparty, limit=limit)
    result["days_requested"] = days
    return result


@investigation_router.get("/api/investigate/subnet/{netuid}/owner-check")
async def api_owner_check(netuid: int, wallets: str = Query("", description="Comma-separated SS58 addresses")):
    parsed: List[str] = [w.strip() for w in wallets.split(",") if w.strip()]
    if len(parsed) > MAX_OWNER_CHECK_WALLETS or not all(_SS58.match(w) for w in parsed):
        raise HTTPException(
            status_code=422,
            detail=f"wallets must be at most {MAX_OWNER_CHECK_WALLETS} SS58 addresses",
        )
    return investigate_owner_check(netuid, parsed)


@investigation_router.post("/api/investigate/ask")
async def api_investigate_ask(ask_in: InvestigateAskIn):
    return build_investigation_report(ask_in.question, netuid=ask_in.netuid, wallet=ask_in.wallet)
