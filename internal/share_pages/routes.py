"""§28 — shareable HTML pages + search API."""

from __future__ import annotations

import html
import logging
import os
from typing import Any, Dict, List

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from internal.share_pages.search import global_search

logger = logging.getLogger(__name__)

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
templates = Jinja2Templates(directory=os.path.join(_REPO, "templates"))

share_router = APIRouter(tags=["share"])


def _public_base(request: Request) -> str:
    base = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    return base or str(request.base_url).rstrip("/")


@share_router.get("/api/search")
async def api_global_search(q: str = Query("", min_length=1), limit: int = Query(8, ge=1, le=20)):
    """Command palette search — subnets, wallets, graded picks."""
    return {"status": "success", "query": q, "results": global_search(q, limit=limit)}


@share_router.get("/subnet/{netuid}")
async def subnet_share_page(request: Request, netuid: int):
    """§28-1 — routable per-subnet analysis page."""
    from internal.analytics.report import build_subnet_report, markdown_subset_html

    report = build_subnet_report(netuid)
    name = report.get("name") or f"SN{netuid}"
    judges = (report.get("sections") or {}).get("judges") or {}
    drivers = (report.get("sections") or {}).get("market_drivers") or {}
    consensus = judges.get("consensus") if isinstance(judges, dict) else {}
    base = _public_base(request)
    page_url = f"{base}/subnet/{netuid}"
    title = f"{name} (SN{netuid}) — SimiVision"
    desc = (drivers.get("headline") or f"Council analysis and market drivers for Bittensor subnet {netuid}.")[:200]
    og_image = f"{base}/static/favicon.svg"
    data_available = bool(report) and (bool(drivers) or bool(judges) or bool(report.get("markdown")))

    return templates.TemplateResponse(
        request,
        "share/subnet_page.html",
        {
            "netuid": netuid,
            "name": name,
            "report": report,
            "judges": judges,
            "consensus": consensus or {},
            "drivers": drivers,
            "digest_html": markdown_subset_html(report.get("markdown") or ""),
            "data_available": data_available,
            "error_reason": None if data_available else "Subnet report data unavailable",
            "page_title": title,
            "page_description": desc,
            "page_url": page_url,
            "og_image_url": og_image,
            "public_base_url": base,
        },
    )


def _wallet_flow_rows(wallet: str, activity: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    if activity and activity.get("status") == "success":
        rows = activity.get("delegation_events") or []
        return rows if isinstance(rows, list) else []
    try:
        from internal.investigation.service import investigate_wallet

        payload = investigate_wallet(wallet, limit=40)
        if payload.get("status") == "success":
            rows = payload.get("delegation_events") or []
            return rows if isinstance(rows, list) else []
    except Exception as exc:
        logger.debug("wallet flow for page failed: %s", exc)
    return []


def _wallet_profile(wallet: str) -> Dict[str, Any]:
    try:
        from internal.whales.service import WhaleIntelligenceService

        profile = WhaleIntelligenceService().get_profile(wallet)
        return profile if isinstance(profile, dict) else {}
    except Exception:
        return {}


def _wallet_subnet_exposure(flow_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate flow rows by netuid for §28-4 mini graph."""
    totals: Dict[int, float] = {}
    for row in flow_rows:
        if not isinstance(row, dict):
            continue
        n = row.get("netuid")
        if n is None:
            continue
        try:
            netuid = int(n)
        except (TypeError, ValueError):
            continue
        amt = row.get("amount_tao") or row.get("amount") or row.get("tao") or 0
        try:
            totals[netuid] = totals.get(netuid, 0.0) + abs(float(amt))
        except (TypeError, ValueError):
            continue
    ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    if not ranked:
        return []
    peak = ranked[0][1] or 1.0
    return [
        {"netuid": n, "amount_tao": round(amt, 4), "pct": round(100.0 * amt / peak, 1)}
        for n, amt in ranked[:8]
    ]


def _wallet_rug_flags(exposure: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rug risk for top exposure subnets (§29-5)."""
    flags: List[Dict[str, Any]] = []
    try:
        from internal.ruggers.watchlist import RuggerWatchlist

        watch = RuggerWatchlist()
        for row in (exposure or [])[:3]:
            netuid = row.get("netuid")
            if netuid is None:
                continue
            risk = watch.get_subnet_risk(int(netuid))
            level = risk.get("risk_level")
            if not level:
                continue
            flags.append(
                {
                    "netuid": int(netuid),
                    "risk_level": level,
                    "rugger_count": risk.get("rugger_count", 0),
                }
            )
    except Exception as exc:
        logger.debug("wallet rug flags failed: %s", exc)
    return flags


@share_router.get("/wallet/{wallet}")
async def wallet_share_page(request: Request, wallet: str):
    """§28-2 — routable wallet explorer page."""
    from internal.investigation.service import investigate_wallet

    wallet = wallet.strip()
    activity = investigate_wallet(wallet, limit=40)
    flow_rows = _wallet_flow_rows(wallet, activity)
    profile = _wallet_profile(wallet)
    exposure = _wallet_subnet_exposure(flow_rows)
    rug_flags = _wallet_rug_flags(exposure)
    data_ok = activity.get("status") == "success"
    base = _public_base(request)
    page_url = f"{base}/wallet/{html.escape(wallet)}"
    short = wallet[:10] + "…" + wallet[-4:] if len(wallet) > 16 else wallet
    title = f"Wallet {short} — SimiVision"
    desc = f"On-chain wallet flows and subnet exposure for {short}."
    og_image = f"{base}/static/favicon.svg"

    return templates.TemplateResponse(
        request,
        "share/wallet_page.html",
        {
            "wallet": wallet,
            "wallet_short": short,
            "activity": activity,
            "flow_rows": flow_rows[:30],
            "profile": profile,
            "exposure": exposure,
            "rug_flags": rug_flags,
            "data_available": data_ok and bool(flow_rows or exposure),
            "error_reason": None if data_ok else activity.get("message", "TaoStats unavailable"),
            "page_title": title,
            "page_description": desc,
            "page_url": page_url,
            "og_image_url": og_image,
            "public_base_url": base,
        },
    )
