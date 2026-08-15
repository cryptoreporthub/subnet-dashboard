"""
FastAPI APIRouter for the Judge Council endpoints.

Provides:
  GET /api/judges          - Score all subnets through the three-judge council
  GET /api/council         - Full merged data pipeline (Blockmachine + TaoStats + TMC + judges)
  GET /api/paper-portfolio - Paper portfolio for all judges
  GET /api/postmortems     - Postmortems for all judges
  GET /judge-council       - Standalone Judge Council HTML page
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from internal.static_version import STATIC_V

logger = logging.getLogger(__name__)

council_router = APIRouter()

JUDGES_SCORING_UNIVERSE = int(os.environ.get("JUDGES_SCORING_UNIVERSE", "20"))
JUDGES_HANDLER_TIMEOUT = float(os.environ.get("JUDGES_HANDLER_TIMEOUT_SECONDS", "3"))
_JUDGES_TTL = float(os.environ.get("JUDGES_CACHE_SECONDS", "60"))
_JUDGES_LOCK = threading.Lock()
_JUDGES_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}
_JUDGES_CACHE_PATH = os.environ.get(
    "JUDGES_CACHE_PATH", os.path.join("data", "judges_cache.json")
)
_COUNCIL_TTL = float(os.environ.get("COUNCIL_CACHE_SECONDS", "60"))
_COUNCIL_LOCK = threading.Lock()
_COUNCIL_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}
_HEAVY_SEM = threading.Semaphore(int(os.environ.get("JUDGES_HEAVY_CONCURRENCY", "2")))
_BG_LOCK = threading.Lock()
_BG_REFRESHING: set[int] = set()


def _persist_judges_cache(payload: Dict[str, Any]) -> None:
    try:
        import json

        path = _JUDGES_CACHE_PATH
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"at": time.time(), "payload": payload}, handle)
        os.replace(tmp, path)
    except Exception as exc:
        logger.warning("judges cache persist failed: %s", exc)


def _load_judges_cache_file() -> Optional[Dict[str, Any]]:
    try:
        import json

        with open(_JUDGES_CACHE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        payload = data.get("payload") if isinstance(data, dict) else None
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def warm_judges_cache() -> Dict[str, Any]:
    """Boot helper — kick background fill so hydrate is less likely to see naked busy."""
    _kick_background_refresh(_JUDGES_CACHE, _JUDGES_LOCK, _api_judges_sync_inner)
    return {"kicked": True}


async def _to_thread_timeout(fn, timeout_s: float, *, label: str):
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning("%s timed out after %.1fs", label, timeout_s)
        raise

_TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "templates",
)


def _cap_subnets_for_judges(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Score only the top-emission subnets so hydration cannot starve /health."""
    if not subnets or len(subnets) <= JUDGES_SCORING_UNIVERSE:
        return subnets
    return sorted(
        subnets,
        key=lambda s: float(s.get("emission", 0) or 0),
        reverse=True,
    )[:JUDGES_SCORING_UNIVERSE]


def _deduplicate_subnets(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate subnets by netuid, keeping the first occurrence."""
    seen = set()
    unique = []
    for sn in subnets:
        nuid = sn.get("netuid", sn.get("id", 0))
        if nuid not in seen:
            seen.add(nuid)
            unique.append(sn)
    return unique


def _get_merged_data():
    """Deprecated — request paths use live/TMC cache + registry only."""
    return None, "none"


def _get_subnets_for_scoring() -> tuple[List[Dict[str, Any]], str]:
    """Return deduped subnets for judge scoring via shared council feed (§30-10)."""
    try:
        from internal.subnets.feed import get_council_subnet_feed

        subnets, source = get_council_subnet_feed(timeout=2)
        subnets = _deduplicate_subnets(subnets)
        if subnets:
            return subnets, source
    except Exception as e:
        logger.warning("Council subnet feed failed: %s", e)
    return [], "none"


def _kick_background_refresh(
    cache: Dict[str, Any],
    lock: threading.Lock,
    build,
) -> None:
    key = id(cache)
    with _BG_LOCK:
        if key in _BG_REFRESHING:
            return
        _BG_REFRESHING.add(key)

    def _run() -> None:
        retry = False
        try:
            if not lock.acquire(blocking=False):
                return
            try:
                if not _HEAVY_SEM.acquire(blocking=False):
                    retry = True
                    return
                try:
                    payload = build()
                    cache["payload"] = payload
                    cache["at"] = time.time()
                    if cache is _JUDGES_CACHE and isinstance(payload, dict) and payload.get("success"):
                        _persist_judges_cache(payload)
                finally:
                    _HEAVY_SEM.release()
            finally:
                lock.release()
        except Exception as exc:
            logger.warning("background judges/council refresh failed: %s", exc)
        finally:
            with _BG_LOCK:
                _BG_REFRESHING.discard(key)
            if retry:
                # Heavy slot contested — try again soon instead of staying cold-busy.
                threading.Timer(
                    5.0,
                    lambda: _kick_background_refresh(cache, lock, build),
                ).start()

    threading.Thread(target=_run, name="judges-cache-refresh", daemon=True).start()


def _cached_or_build(
    cache: Dict[str, Any],
    lock: threading.Lock,
    ttl: float,
    build,
    *,
    busy_fallback: Dict[str, Any],
):
    """Request path never builds — cold miss kicks bg; prefer stale/volume over naked busy."""
    now = time.time()
    cached = cache.get("payload")
    if isinstance(cached, dict) and now - float(cache.get("at") or 0) < ttl:
        return cached
    _kick_background_refresh(cache, lock, build)
    if isinstance(cached, dict):
        return cached
    if cache is _JUDGES_CACHE:
        file_cached = _load_judges_cache_file()
        if isinstance(file_cached, dict):
            out = dict(file_cached)
            meta = dict(out.get("meta") or {})
            meta["source"] = "volume_stale"
            out["meta"] = meta
            # Hydrate memory so subsequent hits skip the file read.
            cache["payload"] = out
            cache["at"] = float(time.time()) - max(ttl, 1.0)  # keep stale so bg still refreshes
            return out
    return busy_fallback


def _aggregate_portfolios(portfolios: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate judge portfolios (matches dashboard + other router work)."""
    return {
        "open_positions": sum(
            int((p.get("summary") or {}).get("open_positions", 0) or 0)
            for p in portfolios.values()
            if isinstance(p, dict)
        ),
        "total_closed": sum(
            int((p.get("summary") or {}).get("total_closed", 0) or 0)
            for p in portfolios.values()
            if isinstance(p, dict)
        ),
        "total_pnl_pct": round(
            sum(
                float((p.get("summary") or {}).get("total_pnl_pct", 0) or 0)
                for p in portfolios.values()
                if isinstance(p, dict)
            ),
            4,
        ),
    }


def _score_all_judges(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from internal.judges.subnet_judges import score_all_subnets

    return _deduplicate_subnets(score_all_subnets(subnets, use_chain=False))


@council_router.get("/api/council")
async def api_council():
    """Full merged data pipeline: Blockmachine + TaoStats + TaoMarketCap + judge scores."""
    try:
        return await _to_thread_timeout(_api_council_sync, JUDGES_HANDLER_TIMEOUT, label="council")
    except asyncio.TimeoutError:
        cached = _COUNCIL_CACHE.get("payload")
        if isinstance(cached, dict):
            return cached
        return {
            "status": "degraded",
            "subnets": [],
            "judges": [],
            "meta": {
                "count": 0,
                "source": "timeout",
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        }


def _api_council_sync():
    return _cached_or_build(
        _COUNCIL_CACHE,
        _COUNCIL_LOCK,
        _COUNCIL_TTL,
        _api_council_sync_inner,
        busy_fallback={
            "status": "degraded",
            "subnets": [],
            "judges": [],
            "meta": {
                "count": 0,
                "source": "busy",
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        },
    )


def _api_council_sync_inner():
    try:
        merged, source = _get_subnets_for_scoring()
        if not merged:
            # Fall back to TMC only
            from fetchers.taomarketcap import get_all_subnets
            merged = get_all_subnets()
            merged = _deduplicate_subnets(merged)
            source = "taomarketcap-fallback"

        if not merged:
            return {
                "status": "degraded",
                "subnets": [],
                "judges": [],
                "meta": {"count": 0, "source": "none", "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
            }

        merged = _cap_subnets_for_judges(merged)

        # Score through the judge council
        try:
            scored = _score_all_judges(merged)
        except Exception as e:
            logger.warning("Judge scoring in council endpoint failed: %s", e)
            scored = []

        return {
            "status": "success",
            "subnets": merged,
            "judges": scored,
            "meta": {
                "count": len(merged),
                "judged": len(scored) if scored else 0,
                "source": source,
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        }
    except Exception as e:
        logger.error("Council API error: %s", e, exc_info=True)
        return {"status": "error", "error": str(e), "subnets": [], "judges": [], "meta": {"count": 0}}


@council_router.get("/api/judges")
async def api_judges():
    """Score ALL subnets with the three-judge council + consensus."""
    try:
        return await _to_thread_timeout(_api_judges_sync, JUDGES_HANDLER_TIMEOUT, label="judges")
    except asyncio.TimeoutError:
        cached = _JUDGES_CACHE.get("payload")
        if isinstance(cached, dict):
            return cached
        return {
            "success": False,
            "error": "timeout",
            "judges": [],
            "count": 0,
        }


def _api_judges_sync():
    return _cached_or_build(
        _JUDGES_CACHE,
        _JUDGES_LOCK,
        _JUDGES_TTL,
        _api_judges_sync_inner,
        busy_fallback={
            "success": False,
            "error": "busy",
            "judges": [],
            "count": 0,
        },
    )


def _api_judges_sync_inner():
    try:
        subnets, source = _get_subnets_for_scoring()
        if subnets:
            subnets = _cap_subnets_for_judges(subnets)
            result = _score_all_judges(subnets)
            logger.info("Judges: scored %d unique subnets (source=%s)", len(result), source)
            return {
                "success": True,
                "judges": result,
                "count": len(result),
                "source": source,
                "meta": {
                    "count": len(result),
                    "degraded_sources": [],
                    "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            }

        return {"success": False, "error": "No subnet data available", "judges": [], "count": 0}
    except Exception as e:
        logger.warning("Judge scoring failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e), "judges": [], "count": 0}


@council_router.get("/api/judges/{netuid}")
async def api_judges_netuid(netuid: int):
    """Return detailed judge breakdown for one subnet."""
    def _build():
        return _api_judges_netuid_sync(netuid)

    try:
        return await _to_thread_timeout(_build, JUDGES_HANDLER_TIMEOUT, label="judges-netuid")
    except asyncio.TimeoutError:
        return {"error": "timeout", "netuid": netuid}


def _api_judges_netuid_sync(netuid: int):
    try:
        subnets, _source = _get_subnets_for_scoring()
        if not subnets:
            return {"error": "subnet not found", "netuid": netuid}

        from internal.judges.subnet_judges import score_subnet

        target = next(
            (s for s in subnets if s.get("netuid") == netuid or s.get("id") == netuid),
            None,
        )
        if target:
            return score_subnet(netuid, target)
    except Exception as e:
        logger.warning("Judge netuid lookup failed for %s: %s", netuid, e)
    return {"error": "subnet not found", "netuid": netuid}


@council_router.get("/api/judges/{judge}/postmortems")
async def api_judge_postmortems(judge: str):
    """Return scientific-method postmortems for a single judge."""
    try:
        from internal.judges import get_judge
        from internal.judges.postmortems import list_for_judge

        name = judge.lower()
        if get_judge(name) is None:
            return {"status": "error", "error": f"Unknown judge: {judge}"}
        return {"status": "success", "judge": name, "postmortems": list_for_judge(name)}
    except Exception as exc:
        logger.warning("api_judge_postmortems failed: %s", exc)
        return {"status": "stub", "judge": judge, "postmortems": [], "error": str(exc)}


@council_router.get("/api/council-ab")
async def api_council_ab(limit: int = 14):
    """Research scorecard for Daily Model vs Judge Council top-five lists."""
    try:
        from internal.council.ab_benchmark import comparison

        return comparison(limit=limit)
    except Exception as exc:
        logger.warning("A/B council comparison failed: %s", exc)
        return {
            "status": "degraded",
            "research_ready": False,
            "snapshot_count": 0,
            "daily_model": {},
            "judge_council": {},
            "snapshots": [],
            "error": str(exc),
        }


@council_router.get("/council-ab", response_class=HTMLResponse)
async def council_ab_page():
    """Serve the research comparison page."""
    path = os.path.join(_TEMPLATES_DIR, "council_ab.html")
    try:
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        return HTMLResponse(content=html.replace("{{ static_v }}", STATIC_V))
    except Exception as exc:
        logger.warning("Council A/B template not found: %s", exc)
        return HTMLResponse(content="<h1>Council comparison unavailable</h1>", status_code=503)


@council_router.get("/api/paper-portfolio")
async def api_paper_portfolio():
    """Return legacy judge portfolios plus the canonical ledger view."""
    try:
        from internal.judges.portfolios import all_portfolios

        portfolios = all_portfolios()
    except Exception as e:
        logger.warning("Portfolio fetch failed: %s", e)
        portfolios = {}
    try:
        from internal.portfolio.engine import build_portfolio_status

        canonical = build_portfolio_status()
    except Exception as e:
        logger.warning("Canonical portfolio fetch failed: %s", e)
        canonical = {"status": "degraded", "error": str(e)}
    return {
        "aggregate": _aggregate_portfolios(portfolios),
        "judges": portfolios,
        "canonical": canonical,
        "source": "legacy_judge_portfolios",
        "canonical_source": "data/predictions.json",
    }


@council_router.get("/api/portfolios")
async def api_portfolios():
    """Return the current paper portfolios for Oracle, Echo and Pulse."""
    try:
        from internal.judges.portfolios import all_portfolios

        return {"status": "success", "portfolios": all_portfolios()}
    except Exception as exc:
        logger.warning("api_portfolios failed: %s", exc)
        return {"status": "stub", "portfolios": {}, "error": str(exc)}


@council_router.get("/api/postmortems")
async def api_postmortems(judge: Optional[str] = None):
    """Return all postmortems, optionally filtered by judge name."""
    try:
        from internal.judges.postmortems import all_postmortems, list_for_judge

        if judge:
            pms = list_for_judge(judge)
            return {"judge": judge, "postmortems": pms if isinstance(pms, list) else []}
        pms = all_postmortems()
        return {"postmortems": pms if isinstance(pms, dict) else {}}
    except Exception as e:
        logger.warning("Postmortem fetch failed: %s", e)
        return {"postmortems": {}}


@council_router.get("/api/postmortems/{judge_name}")
async def api_postmortems_by_judge(judge_name: str):
    """Return postmortems for a specific judge."""
    try:
        from internal.judges.postmortems import list_for_judge

        pms = list_for_judge(judge_name)
        return {"judge": judge_name, "postmortems": pms if isinstance(pms, list) else []}
    except Exception as e:
        logger.warning("Postmortem fetch failed for %s: %s", judge_name, e)
        return {"judge": judge_name, "postmortems": []}


@council_router.get("/judge-council", response_class=HTMLResponse)
async def judge_council_page():
    """Serve the standalone Judge Council page."""
    path = os.path.join(_TEMPLATES_DIR, "judge_council.html")
    try:
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        # Served as raw HTML, not via Jinja — resolve the cache-bust token inline.
        return HTMLResponse(content=html.replace("{{ static_v }}", STATIC_V))
    except Exception as e:
        logger.warning("Judge council template not found: %s", e)
        return HTMLResponse(content="<h1>Judge Council page not available</h1>", status_code=503)
