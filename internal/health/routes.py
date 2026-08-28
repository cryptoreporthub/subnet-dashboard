"""JSON health probe for Fly.io and external monitors (slice 14b)."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from internal.request_executor import to_thread_timeout

health_router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)

OPS_LIVE_HANDLER_TIMEOUT = float(os.environ.get("OPS_LIVE_HANDLER_TIMEOUT_SECONDS", "8"))
SUBNET_INTEGRATIONS_HANDLER_TIMEOUT = float(
    os.environ.get("SUBNET_INTEGRATIONS_HANDLER_TIMEOUT_SECONDS", "8")
)
OPS_EVIDENCE_HANDLER_TIMEOUT = float(os.environ.get("OPS_EVIDENCE_HANDLER_TIMEOUT_SECONDS", "8"))


def ops_live_degraded_payload(*, error: str = "timeout") -> dict:
    """Honest degraded ops/live body — never launder timeout as ok."""
    data_dir = os.environ.get("DATA_DIR", "data")
    return {
        "status": "degraded",
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "live": False,
        "volume": {"path": data_dir, "writable": False},
        "worker_mode": "unknown",
        "worker_peer": {},
        "error": error,
    }


def build_ops_live_report_sync():
    """File/heartbeat-only liveness — no worker HTTP peer on hot paths."""
    from internal.ops.readiness import build_liveness_report

    return build_liveness_report(probe_worker=False)


async def fetch_ops_live_report() -> dict:
    """REQUEST_EXECUTOR + hard timeout so hydrate cannot wedge accept()."""
    try:
        return await to_thread_timeout(
            build_ops_live_report_sync,
            OPS_LIVE_HANDLER_TIMEOUT,
            label="ops-live",
        )
    except asyncio.TimeoutError:
        return ops_live_degraded_payload(error="timeout")


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
    return await fetch_ops_live_report()


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

    try:
        return await to_thread_timeout(
            build_evidence_report, OPS_EVIDENCE_HANDLER_TIMEOUT, label="ops-evidence"
        )
    except asyncio.TimeoutError:
        return {
            "status": "timeout",
            "error": "timeout",
            "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "alerts": [],
            "paths": {},
            "combined_angles": None,
            "pick_audit": {},
            "pump_desk": {},
            "learning_outcomes": {},
            "accuracy_lift": {"data_available": False},
            "attribution_quality": {},
            "weight_audit": {},
            "capture": {},
        }


@health_router.get("/api/ops/desearch-spend")
async def api_desearch_spend(recent: int = 25):
    """Rolling DeSearch API spend from X-Desearch-* response headers."""
    from internal.integrations.desearch_spend import get_spend_summary

    return get_spend_summary(recent_limit=max(1, min(recent, 100)))


@health_router.get("/api/subnet-integrations")
async def api_subnet_integrations():
    """Live Bittensor subnet integration status (Finney + SN19/22/64/118)."""
    from internal.integrations.status import build_integrations_status

    try:
        return await to_thread_timeout(
            build_integrations_status,
            SUBNET_INTEGRATIONS_HANDLER_TIMEOUT,
            label="subnet-integrations",
        )
    except asyncio.TimeoutError:
        return {
            "integrations": [],
            "candidates": [],
            "catalog": {},
            "connected_count": 0,
            "integration_total": 0,
            "target_minimum": 3,
            "ready_for_launch": False,
            "desearch_spend": {},
            "error": "timeout",
            "cached": False,
        }


@health_router.get("/api/subnet-integrations/signals")
async def api_subnet_integration_signals():
    """Macro mood signals from connected subnet APIs (Wave E)."""
    from internal.integrations.signals import build_macro_signals

    return build_macro_signals()
