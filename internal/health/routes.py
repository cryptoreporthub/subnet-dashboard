"""JSON health probe for Fly.io and external monitors (slice 14b)."""

from __future__ import annotations

from fastapi import APIRouter, Query

health_router = APIRouter(tags=["health"])


@health_router.get("/api/data-freshness")
async def api_data_freshness():
    """Live-data freshness for the on-chain feed (audit finding #1)."""
    from internal.live_subnets import live_data_freshness

    return live_data_freshness()


@health_router.get("/api/health")
async def api_health_check():
    """JSON health probe mirroring plain-text ``/health``."""
    return {"status": "ok"}


@health_router.get("/api/ops/live")
async def api_ops_live():
    """Ultra-fast liveness for Fly/monitors — no feed probes or network."""
    from internal.ops.readiness import build_liveness_report

    return build_liveness_report()


@health_router.get("/api/ops/worker-peer")
async def api_ops_worker_peer():
    """Minimal worker liveness for split_v2 web HTTP probe (file heartbeat only)."""
    from fastapi import HTTPException

    from internal.run_mode import is_worker_mode

    if not is_worker_mode():
        # ponytail: flycast can route to web — never recurse HTTP peer probe on web.
        raise HTTPException(status_code=404, detail="worker_peer_only_on_worker_machine")
    from internal.worker_peer import get_worker_peer

    return {"worker_peer": get_worker_peer()}


@health_router.get("/api/ops/readiness")
async def api_ops_readiness(refresh: bool = Query(default=False)):
    """Single prod readiness probe: volume, scheduler, feed, creds (§33)."""
    from internal.ops.readiness_cache import get_readiness_report

    return await get_readiness_report(force=refresh)


@health_router.get("/api/ops/evidence")
async def api_ops_evidence():
    """Ops evidence bundle: pick audit + pump desk + learning outcomes artifacts."""
    from internal.ops.evidence import build_evidence_report

    return build_evidence_report()


@health_router.get("/api/ops/desearch-spend")
async def api_desearch_spend(recent: int = 25):
    """Rolling DeSearch API spend from X-Desearch-* response headers."""
    from internal.integrations.desearch_spend import get_spend_summary

    return get_spend_summary(recent_limit=max(1, min(recent, 100)))


@health_router.get("/api/subnet-integrations")
async def api_subnet_integrations():
    """Live Bittensor subnet integration status (Finney + SN19/22/64/118)."""
    from internal.integrations.status import build_integrations_status

    return build_integrations_status()


@health_router.get("/api/subnet-integrations/signals")
async def api_subnet_integration_signals():
    """Macro mood signals from connected subnet APIs (Wave E)."""
    from internal.integrations.signals import build_macro_signals

    return build_macro_signals()
