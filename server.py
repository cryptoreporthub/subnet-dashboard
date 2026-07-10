import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from internal.council.mindmap_bridge import MindmapBridge
from internal.whales.routes import whales_router

logger = logging.getLogger("server")

try:
    from internal.judges.council_routes import council_router

    _COUNCIL_ROUTES = True
except Exception as _council_exc:  # pragma: no cover - defensive import guard
    logger.warning("Council judge routes unavailable: %s", _council_exc)
    _COUNCIL_ROUTES = False

try:
    from internal.learning.routes import learning_router

    _LEARNING_ROUTES = True
except Exception as _learning_exc:  # pragma: no cover - defensive import guard
    logger.warning("Learning loop routes unavailable: %s", _learning_exc)
    _LEARNING_ROUTES = False

try:
    from internal.ruggers.routes import ruggers_router

    _RUGGERS_ROUTES = True
except Exception as _ruggers_exc:  # pragma: no cover - defensive import guard
    logger.warning("Ruggers watchlist routes unavailable: %s", _ruggers_exc)
    _RUGGERS_ROUTES = False

try:
    from internal.indicators.routes import indicators_router

    _INDICATORS_ROUTES = True
except Exception as _indicators_exc:  # pragma: no cover - defensive import guard
    logger.warning("Indicator routes unavailable: %s", _indicators_exc)
    _INDICATORS_ROUTES = False

try:
    from internal.oracle.routes import oracle_router

    _ORACLE_ROUTES = True
except Exception as _oracle_exc:  # pragma: no cover - defensive import guard
    logger.warning("Oracle routes unavailable: %s", _oracle_exc)
    _ORACLE_ROUTES = False

try:
    from internal.analytics.routes import analytics_router

    _ANALYTICS_ROUTES = True
except Exception as _analytics_exc:  # pragma: no cover - defensive import guard
    logger.warning("Analytics routes unavailable: %s", _analytics_exc)
    _ANALYTICS_ROUTES = False

# Council pick engine (guarded so a broken/missing engine module can never stop
# the app from booting — the picks endpoints degrade to a safe fallback).
try:
    from fetchers.taomarketcap import get_all_subnets
    from internal.council.state_vector import (
        score_subnet_for_hour,
        score_subnet_for_day,
    )
    from internal.council.hourly_pick import select_hourly_pick
    from internal.council.daily_pick_engine import get_or_create_today_pick

    _PICKS_ENGINE = True
except Exception as _exc:  # pragma: no cover - defensive import guard
    logger.warning("Pick engine unavailable, using fallbacks: %s", _exc)
    _PICKS_ENGINE = False

app = FastAPI(title="Subnet Dashboard")
app.include_router(whales_router)
if _COUNCIL_ROUTES:
    app.include_router(council_router)
if _LEARNING_ROUTES:
    app.include_router(learning_router)
if _RUGGERS_ROUTES:
    app.include_router(ruggers_router)
if _INDICATORS_ROUTES:
    app.include_router(indicators_router)
if _ORACLE_ROUTES:
    app.include_router(oracle_router)
if _ANALYTICS_ROUTES:
    app.include_router(analytics_router)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

_static_dir = os.path.join(BASE_DIR, "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# Paths that get a short public cache to keep the dashboard snappy on Fly.io.
_CACHE_PATHS = ("/api/registry", "/api/summary", "/api/stats")


def load_data(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return {}


def _load_subnets_source():
    """Return subnets for /api/subnets: live TaoMarketCap when available, else committed registry."""
    try:
        from fetchers.taomarketcap import get_all_subnets

        live = get_all_subnets()
        if live:
            return live
    except Exception:
        pass
    return list(load_data("config/registry.json").values())


def _consensus_map():
    """Build a subnet_id -> consensus decision lookup from the latest soul-map output."""
    soul_map = load_data("data/soul_map.json")
    last_output = soul_map.get("soul_map_state", {}).get("last_selector_output", {})
    decisions = last_output.get("decisions", [])
    return {d["subnet_id"]: d for d in decisions if "subnet_id" in d}


@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    """Allow dashboard embedding and cross-origin API access (parity with prior Flask behavior)."""
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["X-Frame-Options"] = "ALLOWALL"
    if request.url.path in _CACHE_PATHS:
        response.headers["Cache-Control"] = "public, max-age=30"
    return response


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/daily-rotation")
def daily_rotation():
    """Return the latest daily rotation decisions plus live recommendations."""
    soul_map = load_data("data/soul_map.json")
    last_output = soul_map.get("soul_map_state", {}).get("last_selector_output", {})
    recommendations = MindmapBridge().get_brain_recommendations()
    return {
        "status": "success",
        "data": {
            "date": last_output.get("date"),
            "decisions": last_output.get("decisions", []),
            "recommendations": recommendations.get("recommendations", {}),
            "updated_at": soul_map.get("soul_map_state", {}).get("updated_at"),
        },
    }


@app.get("/api/registry")
def get_registry():
    data = load_data("config/registry.json")
    consensus = _consensus_map()
    # Enrich each entry with consensus data (additive, backward-compatible).
    enriched = {}
    for key, value in data.items():
        item = dict(value)
        subnet_id = item.get("id", int(key))
        item.setdefault("id", subnet_id)
        decision = consensus.get(subnet_id)
        if decision:
            item["consensus"] = {
                "score": decision.get("consensus_score"),
                "recommended_action": decision.get("recommended_action"),
                "expert_breakdown": decision.get("expert_breakdown"),
            }
        enriched[key] = item
    return enriched


@app.get("/api/subnets")
def list_subnets(request: Request):
    """List subnets with optional filtering, sorting, and pagination."""
    # Prefer LIVE TaoMarketCap data (real 24h/7d/30d); fall back to the committed registry.
    source = _load_subnets_source()
    items = []
    for s in source:
        item = dict(s)
        item.setdefault("id", s.get("netuid", 0))
        items.append(item)

    params = request.query_params
    status_filter = params.get("status")
    if status_filter:
        statuses = {s.strip().lower() for s in status_filter.split(",")}
        items = [i for i in items if str(i.get("status", "")).lower() in statuses]

    sort_field = params.get("sort", "id")
    order = params.get("order", "asc").lower()
    reverse = order == "desc"

    def sort_key(item):
        value = item.get(sort_field)
        if value is None and sort_field == "total_stake":
            value = item.get("staking_data", {}).get("total_stake")
        elif value is None and sort_field == "apy":
            value = item.get("staking_data", {}).get("apy")
        if isinstance(value, (int, float)):
            return (0, value)
        if isinstance(value, str):
            return (1, value.lower())
        return (2, "")

    items = sorted(items, key=sort_key, reverse=reverse)

    try:
        limit = int(params.get("limit", 0))
        offset = int(params.get("offset", 0))
    except ValueError:
        limit = 0
        offset = 0

    total = len(items)
    if offset:
        items = items[offset:]
    if limit > 0:
        items = items[:limit]

    return {"status": "success", "meta": {"total": total, "limit": limit, "offset": offset}, "subnets": items}


@app.get("/api/subnet/{subnet_id}")
def get_subnet(subnet_id: int):
    data = load_data("config/registry.json")
    subnet_data = data.get(str(subnet_id))
    if subnet_data is None:
        return JSONResponse(status_code=404, content={"error": "Subnet not found"})
    return {"subnet_id": subnet_id, "data": subnet_data}


@app.get("/api/summary")
def get_summary():
    """Lightweight aggregated hero-card data for the dashboard."""
    data = load_data("config/registry.json")
    subnets = list(data.values())

    status_counts = {}
    total_stake = 0.0
    total_emission = 0.0
    total_mentions = 0
    overvalued = 0
    apys = []
    last_updated = None

    for subnet in subnets:
        status = subnet.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        total_stake += subnet.get("staking_data", {}).get("total_stake", 0.0) or 0.0
        total_emission += subnet.get("emission", 0.0) or 0.0
        total_mentions += subnet.get("social_mentions", 0) or 0
        if subnet.get("is_overvalued"):
            overvalued += 1
        apy = subnet.get("staking_data", {}).get("apy")
        if apy is not None:
            apys.append(apy)
        updated = subnet.get("last_updated")
        if updated and (last_updated is None or updated > last_updated):
            last_updated = updated

    # Featured highlights: top emitter, top staked, top APY, most mentioned.
    def top_by(field, n=1):
        def key(s):
            if field in ("total_stake", "apy"):
                return s.get("staking_data", {}).get(field, 0.0) or 0.0
            return s.get(field, 0.0) or 0.0

        ranked = sorted(subnets, key=key, reverse=True)[:n]
        return [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "status": s.get("status"),
                field: key(s),
            }
            for s in ranked
        ]

    def top_by_consensus(n=1):
        ranked = sorted(
            subnets,
            key=lambda s: (s.get("consensus", {}) or {}).get("score", 0.0) or 0.0,
            reverse=True,
        )[:n]
        return [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "status": s.get("status"),
                "consensus_score": (s.get("consensus", {}) or {}).get("score"),
                "recommended_action": (s.get("consensus", {}) or {}).get(
                    "recommended_action"
                ),
            }
            for s in ranked
        ]

    def riskiest_by_consensus(n=1):
        flagged = [
            s
            for s in subnets
            if s.get("status") in ("at-risk", "deprecated") or s.get("is_overvalued")
        ]
        ranked = sorted(
            flagged,
            key=lambda s: (s.get("consensus", {}) or {}).get("score", 1.0) or 1.0,
        )[:n]
        return [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "status": s.get("status"),
                "consensus_score": (s.get("consensus", {}) or {}).get("score"),
                "recommended_action": (s.get("consensus", {}) or {}).get(
                    "recommended_action"
                ),
            }
            for s in ranked
        ]

    total = len(subnets) or 1
    status_distribution = {
        status: round(count / total, 4) for status, count in status_counts.items()
    }
    network_health = round(status_counts.get("active", 0) / total, 4)
    flagged_count = (
        status_counts.get("at-risk", 0)
        + status_counts.get("deprecated", 0)
        + overvalued
    )

    return {
        "status": "success",
        "summary": {
            "total_subnets": len(subnets),
            "status_counts": status_counts,
            "status_distribution": status_distribution,
            "active_count": status_counts.get("active", 0),
            "at_risk_count": status_counts.get("at-risk", 0),
            "deprecated_count": status_counts.get("deprecated", 0),
            "unknown_count": status_counts.get("unknown", 0),
            "total_stake": round(total_stake, 4),
            "total_emission": round(total_emission, 4),
            "total_social_mentions": total_mentions,
            "overvalued_count": overvalued,
            "flagged_count": flagged_count,
            "avg_apy": round(sum(apys) / len(apys), 6) if apys else 0.0,
            "network_health": network_health,
            "last_updated": last_updated,
        },
        "highlights": {
            "top_emitter": top_by("emission", 1),
            "top_staked": top_by("total_stake", 1),
            "top_apy": top_by("apy", 1),
            "most_mentioned": top_by("social_mentions", 1),
            "top_consensus": top_by_consensus(1),
            "riskiest": riskiest_by_consensus(1),
        },
    }


@app.get("/api/stats")
def get_stats():
    """Aggregated registry intelligence for dashboard hero panels."""
    data = load_data("config/registry.json")
    subnets = list(data.values())

    status_counts = {}
    total_stake = 0.0
    total_emission = 0.0
    total_mentions = 0
    overvalued = 0
    apys = []

    for subnet in subnets:
        status = subnet.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        total_stake += subnet.get("staking_data", {}).get("total_stake", 0.0) or 0.0
        total_emission += subnet.get("emission", 0.0) or 0.0
        total_mentions += subnet.get("social_mentions", 0) or 0
        if subnet.get("is_overvalued"):
            overvalued += 1
        apy = subnet.get("staking_data", {}).get("apy")
        if apy is not None:
            apys.append(apy)

    def top_n(field, n=5):
        def key(s):
            value = s.get(field, 0) or 0
            if field in ("total_stake", "apy"):
                value = s.get("staking_data", {}).get(field, 0) or 0
            return value

        ranked = sorted(subnets, key=key, reverse=True)[:n]
        return [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "status": s.get("status"),
                "emission": s.get("emission"),
                "total_stake": s.get("staking_data", {}).get("total_stake"),
                "apy": s.get("staking_data", {}).get("apy"),
                "social_mentions": s.get("social_mentions"),
                "is_overvalued": s.get("is_overvalued"),
            }
            for s in ranked
        ]

    flagged = [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "status": s.get("status"),
            "risk_flags": s.get("risk_flags", []),
            "is_overvalued": s.get("is_overvalued"),
            "emission": s.get("emission"),
        }
        for s in subnets
        if s.get("status") in ("at-risk", "deprecated") or s.get("is_overvalued")
    ]

    return {
        "status": "success",
        "summary": {
            "total_subnets": len(subnets),
            "status_counts": status_counts,
            "total_stake": round(total_stake, 4),
            "total_emission": round(total_emission, 4),
            "total_social_mentions": total_mentions,
            "overvalued_count": overvalued,
            "avg_apy": round(sum(apys) / len(apys), 6) if apys else 0.0,
        },
        "top_emitters": top_n("emission"),
        "top_staked": top_n("total_stake"),
        "top_mentioned": top_n("social_mentions"),
        "flagged_subnets": flagged,
    }


@app.get("/api/soul-map")
def get_soul_map():
    """Expose the persisted Soul-Map state and feedback history."""
    data = load_data("data/soul_map.json")
    return {"status": "success", "data": data}


@app.get("/api/recommendations")
def get_recommendations():
    """Live Brain recommendations derived from the current registry."""
    bridge = MindmapBridge()
    return {"status": "success", "data": bridge.get_brain_recommendations()}


@app.post("/api/mindmap/feedback")
async def post_feedback(request: Request):
    try:
        feedback = await request.json()
    except Exception:
        feedback = None
    return {"status": "received", "feedback": feedback}


@app.get("/health")
def health():
    return PlainTextResponse("OK")


# ---------------------------------------------------------------------------
# SimiVision picks (ported from server_original.py onto the FastAPI foundation)
#
# NOTE: pick-generation is read-only here. The scenario-memory and pick-history
# *recording* side-effects from the original _ordered_hour_picks are deferred to
# their own slices (/api/scenario-memory, /api/pick-history) so this slice stays
# atomic. Subnets come from the deduped taomarketcap source, so picks never
# repeat a subnet ("Minos multiple times" was upstream duplication, now fixed).
# ---------------------------------------------------------------------------

# taomarketcap-shaped static fallback used when live/cached data is unavailable.
_STATIC_SUBNETS = [
    {"netuid": 29, "name": "Coldint", "emission": 3.0, "apy": 42.5, "volume": 1250000,
     "market_cap": 45000000, "price": 28.50, "price_change_24h": 12.3,
     "price_change_7d": 18.2, "price_change_30d": 24.9, "status": "active"},
    {"netuid": 19, "name": "Inference", "emission": 2.1, "apy": 38.2, "volume": 980000,
     "market_cap": 32000000, "price": 15.20, "price_change_24h": 8.7,
     "price_change_7d": 12.1, "price_change_30d": 16.8, "status": "active"},
    {"netuid": 12, "name": "Compute", "emission": 1.8, "apy": 35.1, "volume": 750000,
     "market_cap": 28000000, "price": 12.40, "price_change_24h": 5.2,
     "price_change_7d": 9.4, "price_change_30d": 13.0, "status": "active"},
]


def _get_subnets_with_source():
    """Return (subnets, source) for picks, deduped by netuid; static fallback otherwise."""
    if _PICKS_ENGINE:
        try:
            subnets = get_all_subnets()
            if subnets:
                deduped = {}
                for s in subnets:
                    deduped.setdefault(s.get("netuid"), s)
                return list(deduped.values()), "taomarketcap"
        except Exception as exc:
            logger.warning("Error fetching from taomarketcap: %s", exc)
    return [dict(s) for s in _STATIC_SUBNETS], "static-fallback"


def _market_mood_proxy(subnets: List[Dict[str, Any]]) -> float:
    """Market-wide 24h change proxy from the average subnet change."""
    changes = []
    for sn in subnets or []:
        try:
            changes.append(float(sn.get("price_change_24h", 0) or 0))
        except (TypeError, ValueError):
            continue
    return sum(changes) / len(changes) if changes else 0.0


def _highest_emission_pick(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pick-shaped fallback using the highest-emission subnet."""
    best = max(subnets, key=lambda s: s.get("emission", 0) or 0) if subnets else {}
    return {
        "subnet": {"netuid": best.get("netuid"), "name": best.get("name"), "symbol": best.get("symbol")},
        "score": 0.0,
        "confidence": 0.0,
        "expert_contributions": {},
        "scenario_tags": {"fallback": "highest-emission"},
        "signals": {
            "price_change_24h": best.get("price_change_24h"),
            "price_change_7d": best.get("price_change_7d"),
            "emission": best.get("emission"),
            "apy": best.get("apy"),
            "volume": best.get("volume"),
        },
        "action": "long",
    }


def _safe_simivision_payload() -> Dict[str, Any]:
    """SimiVision panel: top-3 subnets by emission / APY / volume (distinct subnets)."""
    subnets, source = _get_subnets_with_source()
    ranked = sorted(
        subnets,
        key=lambda s: (s.get("emission", 0), s.get("apy", 0), s.get("volume", 0)),
        reverse=True,
    )
    top = []
    for idx, sn in enumerate(ranked[:3], start=1):
        top.append({
            "rank": idx,
            "netuid": sn.get("netuid"),
            "name": sn.get("name"),
            "emission": sn.get("emission", 0),
            "apy": sn.get("apy", 0),
            "price_change_24h": sn.get("price_change_24h", 0),
            "conviction": min(95, 72 + int(abs(sn.get("price_change_24h", 0))) + int(sn.get("apy", 0) / 4)),
            "recommendation": "BUY" if idx == 1 else ("HOLD" if idx == 2 else "WATCH"),
        })
    return {
        "status": "success",
        "data": {
            "top": top,
            "meta": {
                "count": len(subnets),
                "source": source,
                "updated_at": datetime.utcnow().isoformat() + "Z",
            },
        },
    }


def _build_hour_pick_payload(sn: Dict[str, Any], score: Dict[str, Any]) -> Dict[str, Any]:
    """Format a subnet + hour state-vector into the public hour-pick shape."""
    return {
        "subnet": {"netuid": sn.get("netuid"), "name": sn.get("name"), "symbol": sn.get("symbol")},
        "score": score["total_score"],
        "confidence": score["confidence"],
        "expert_contributions": score["expert_contributions"],
        "scenario_tags": score["scenario_tags"],
        "signals": {
            "price_change_24h": sn.get("price_change_24h"),
            "price_change_7d": sn.get("price_change_7d"),
            "emission": sn.get("emission"),
            "apy": sn.get("apy"),
            "volume": sn.get("volume"),
        },
        "action": "long",
    }


def _ordered_hour_picks(subnets, market_context, limit: int = 3) -> List[Dict[str, Any]]:
    """Canonical ordered hourly picks: RedTeam-audited #1 (select_hourly_pick),
    then distinct fill by raw hour score. Excludes the #1 netuid so no subnet
    repeats. (Scenario/history recording deferred to their own slices.)"""
    picks: List[Dict[str, Any]] = []
    if not subnets:
        return picks

    audited = None
    if _PICKS_ENGINE:
        try:
            audited = select_hourly_pick(subnets, market_context)
        except Exception as exc:
            logger.warning("select_hourly_pick failed: %s", exc)
    if not audited:
        audited = _highest_emission_pick(subnets)

    top_netuid = None
    if isinstance(audited, dict) and isinstance(audited.get("subnet"), dict):
        top_netuid = audited["subnet"].get("netuid")
        if "signals" not in audited:
            src = next((s for s in subnets if s.get("netuid") == top_netuid), {})
            audited["signals"] = {
                "price_change_24h": src.get("price_change_24h"),
                "price_change_7d": src.get("price_change_7d"),
                "emission": src.get("emission"),
                "apy": src.get("apy"),
                "volume": src.get("volume"),
            }

    def _unify(payload, sn):
        subnet = payload.get("subnet") if isinstance(payload.get("subnet"), dict) else {}
        unified = dict(payload)
        unified.setdefault("netuid", subnet.get("netuid", sn.get("netuid")))
        unified.setdefault("name", subnet.get("name", sn.get("name")))
        unified.setdefault("symbol", subnet.get("symbol", sn.get("symbol")))
        unified.setdefault("score", payload.get("score", 0.0))
        unified.setdefault("confidence", payload.get("confidence", 0.0))
        unified.setdefault("scenario_tags", payload.get("scenario_tags", {}))
        unified.setdefault("signals", payload.get("signals", {}))
        return unified

    src = next((s for s in subnets if s.get("netuid") == top_netuid), {})
    picks.append(_unify(audited, src))

    if _PICKS_ENGINE:
        scored = []
        for sn in subnets:
            if top_netuid is not None and sn.get("netuid") == top_netuid:
                continue
            try:
                scored.append({"subnet": sn, "score": score_subnet_for_hour(sn, market_context)})
            except Exception as exc:
                logger.warning("score_subnet_for_hour failed for SN%s: %s", sn.get("netuid"), exc)
        scored.sort(key=lambda x: x["score"]["total_score"], reverse=True)
        for item in scored[: max(0, limit - len(picks))]:
            picks.append(_unify(_build_hour_pick_payload(item["subnet"], item["score"]), item["subnet"]))

    return picks[:limit]


@app.get("/api/simivision")
def api_simivision():
    """SimiVision intelligence panel — top ranked subnets (distinct)."""
    return _safe_simivision_payload()


@app.get("/api/top-picks")
def api_top_picks():
    """Top 3 subnets by short-horizon (hour) and 24h (day) Council scores."""
    subnets, _ = _get_subnets_with_source()
    if not _PICKS_ENGINE:
        return {"hour_picks": [], "day_picks": [], "error": "pick engine unavailable"}
    market_context = {"tao_change_24h": _market_mood_proxy(subnets)}
    hour_scored, day_scored = [], []
    for sn in subnets:
        try:
            hour_scored.append({"subnet": sn, "score": score_subnet_for_hour(sn, market_context)})
            day_scored.append({"subnet": sn, "score": score_subnet_for_day(sn, market_context)})
        except Exception as exc:
            logger.warning("scoring failed for SN%s: %s", sn.get("netuid"), exc)
    hour_scored.sort(key=lambda x: x["score"]["total_score"], reverse=True)
    day_scored.sort(key=lambda x: x["score"]["total_score"], reverse=True)

    def _format(item):
        sn, sc = item["subnet"], item["score"]
        return {
            "netuid": sn.get("netuid"),
            "name": sn.get("name"),
            "symbol": sn.get("symbol"),
            "score": sc["total_score"],
            "confidence": sc["confidence"],
            "expert_contributions": sc["expert_contributions"],
            "signals": {
                "price_change_24h": sn.get("price_change_24h"),
                "price_change_7d": sn.get("price_change_7d"),
                "emission": sn.get("emission"),
                "apy": sn.get("apy"),
                "volume": sn.get("volume"),
            },
            "scenario_tags": sc["scenario_tags"],
        }

    return {
        "hour_picks": [_format(i) for i in hour_scored[:3]],
        "day_picks": [_format(i) for i in day_scored[:3]],
    }


@app.get("/api/daily-pick")
def api_daily_pick():
    """Today's audited daily pick from the Council engine."""
    subnets, _ = _get_subnets_with_source()
    if not _PICKS_ENGINE:
        return {"status": "error", "date": datetime.utcnow().date().isoformat(),
                "action": "HOLD", "reason": "pick engine unavailable", "pick": None}
    market_context = {"tao_change_24h": _market_mood_proxy(subnets)}
    try:
        return get_or_create_today_pick(subnets, market_context)
    except Exception as e:
        logger.error("Error fetching daily pick: %s", e)
        return {"status": "error", "date": datetime.utcnow().date().isoformat(),
                "action": "HOLD", "reason": str(e), "pick": None}


@app.get("/api/top-pick/day")
def api_top_pick_day():
    """Top pick for the current day, with a safe highest-emission fallback."""
    subnets, _ = _get_subnets_with_source()
    day_pick = None
    if _PICKS_ENGINE:
        market_context = {"tao_change_24h": _market_mood_proxy(subnets)}
        try:
            raw = get_or_create_today_pick(subnets, market_context)
            day_pick = raw.get("pick") if isinstance(raw, dict) and raw.get("pick") else raw
        except Exception as exc:
            logger.error("Error selecting daily pick: %s", exc)
    if not day_pick:
        return {"picks": [_highest_emission_pick(subnets)]}
    return {"picks": [day_pick]}


@app.get("/api/top-pick/hour")
def api_top_pick_hour():
    """Top short-horizon picks (audited #1 + distinct fill), with fallback."""
    subnets, _ = _get_subnets_with_source()
    market_context = {"tao_change_24h": _market_mood_proxy(subnets)}
    try:
        picks = _ordered_hour_picks(subnets, market_context, limit=3)
        if picks:
            return {"picks": picks}
    except Exception as e:
        logger.error("Error fetching hour pick: %s", e)
    return {"picks": [_highest_emission_pick(subnets)]}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 50745))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
