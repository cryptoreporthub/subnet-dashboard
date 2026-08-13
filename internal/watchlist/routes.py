"""§17.F1 — watchlist HTTP routes."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from internal.watchlist.store import load_watchlist, save_watchlist

watchlist_router = APIRouter(tags=["watchlist"])
_OWNER_COOKIE = "message-intel-owner"
_OWNER_SIGNING_SECRET = os.environ.get("SESSION_SECRET", "").strip() or secrets.token_urlsafe(32)


class WatchlistPut(BaseModel):
    netuids: List[Any] = Field(default_factory=list)


class WatchlistThreshold(BaseModel):
    netuid: int
    threshold: Optional[float] = Field(default=None, ge=0, le=100)


def _browser_owner(request: Request, response: Response) -> str:
    raw = str(request.cookies.get(_OWNER_COOKIE) or "")
    secret = _OWNER_SIGNING_SECRET.encode("utf-8")
    if "." in raw:
        nonce, signature = raw.split(".", 1)
        expected = hmac.new(secret, nonce.encode("utf-8"), hashlib.sha256).hexdigest()
        if nonce and hmac.compare_digest(signature, expected):
            return f"browser:{nonce}"
    nonce = secrets.token_urlsafe(24)
    signature = hmac.new(secret, nonce.encode("utf-8"), hashlib.sha256).hexdigest()
    response.set_cookie(
        _OWNER_COOKIE,
        f"{nonce}.{signature}",
        max_age=60 * 60 * 24 * 180,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https" or bool(os.environ.get("REPLIT_DEPLOYMENT")),
    )
    return f"browser:{nonce}"


def _upgrade() -> Dict[str, Any]:
    return {
        "status": "upgrade_required",
        "feature": "My Desk watchlist",
        "required_tier": "pro",
        "netuids": [],
        "thresholds": {},
        "upgrade_prompt": {
            "title": "Upgrade to PRO",
            "body": "My Desk watchlists and alert thresholds are part of PRO.",
            "cta": "Beta access may still unlock this surface; no payment flow is implemented.",
        },
    }


@watchlist_router.get("/api/watchlist/link-code")
async def api_watchlist_link_code(request: Request, response: Response) -> Dict[str, Any]:
    owner = _browser_owner(request, response)
    from internal.watchlist.store import create_link_code

    return {"status": "ok", "code": create_link_code(owner)}


@watchlist_router.get("/api/watchlist")
async def api_watchlist_get(request: Request, response: Response) -> Dict[str, Any]:
    owner = _browser_owner(request, response)
    data = load_watchlist(owner=owner)
    return {
        "status": "ok",
        "netuids": data.get("netuids") or [],
        "thresholds": data.get("thresholds") or {},
        "updated_at": data.get("updated_at"),
    }


@watchlist_router.put("/api/watchlist")
async def api_watchlist_put(request: Request, response: Response, body: WatchlistPut) -> Dict[str, Any]:
    owner = _browser_owner(request, response)
    current = load_watchlist(owner=owner)
    saved = save_watchlist(
        list(body.netuids),
        thresholds=current.get("thresholds") or {},
        alerts=current.get("alerts") or {},
        owner=owner,
    )
    return {
        "status": "ok",
        "netuids": saved["netuids"],
        "thresholds": saved.get("thresholds") or {},
        "updated_at": saved["updated_at"],
    }


@watchlist_router.get("/api/watchlist/thresholds")
async def api_watchlist_thresholds_get(request: Request, response: Response) -> Dict[str, Any]:
    owner = _browser_owner(request, response)
    data = load_watchlist(owner=owner)
    return {
        "status": "ok",
        "thresholds": data.get("thresholds") or {},
        "updated_at": data.get("updated_at"),
    }


@watchlist_router.put("/api/watchlist/thresholds")
async def api_watchlist_thresholds_put(request: Request, response: Response, body: WatchlistThreshold) -> Dict[str, Any]:
    owner = _browser_owner(request, response)
    data = load_watchlist(owner=owner)
    thresholds = dict(data.get("thresholds") or {})
    if body.threshold is None:
        thresholds.pop(str(body.netuid), None)
    else:
        thresholds[str(body.netuid)] = float(body.threshold)
    saved = save_watchlist(
        data.get("netuids") or [],
        thresholds=thresholds,
        alerts=data.get("alerts") or {},
        owner=owner,
    )
    return {
        "status": "ok",
        "thresholds": saved.get("thresholds") or {},
        "updated_at": saved["updated_at"],
    }
