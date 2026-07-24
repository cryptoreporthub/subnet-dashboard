"""JSON health probe for Fly.io and external monitors (slice 14b)."""

from __future__ import annotations

from fastapi import APIRouter

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


@health_router.get("/api/ops/readiness")
async def api_ops_readiness():
    """Single prod readiness probe: volume, scheduler, feed, creds (§33)."""
    from internal.ops.readiness import build_readiness_report

    return build_readiness_report()


@health_router.get("/api/ops/llm-cost")
async def api_ops_llm_cost():
    """Rolling SimiVision chat token usage + estimated Chutes cost."""
    from internal.ops.llm_cost import build_llm_cost_report

    return build_llm_cost_report()


@health_router.get("/api/subnet-integrations")
async def api_subnet_integrations():
    """Live Bittensor subnet integration status."""
    from internal.integrations.status import build_integrations_status

    return build_integrations_status()


@health_router.get("/api/subnet-integrations/signals")
async def api_subnet_integration_signals():
    """Macro mood signals from connected subnet APIs."""
    from internal.integrations.signals import build_macro_signals

    return build_macro_signals()
