"""Prometheus gauges refreshed from existing freshness/scheduler state()."""

from __future__ import annotations

from typing import Any, Dict, Optional

from prometheus_client import Gauge, generate_latest
from starlette.requests import Request
from starlette.responses import Response

_SOURCES = (
    "registry",
    "soul_map",
    "recommendations",
    "watchlist",
    "signal_timeline",
    "price_cache",
)

LIVE_AGE_SECONDS = Gauge("subnet_live_age_seconds", "Age of live on-chain cache in seconds")
LIVE_STALE = Gauge("subnet_live_stale", "1 if live on-chain feed is stale")
SOURCE_AGE_SECONDS = Gauge(
    "subnet_source_age_seconds",
    "Age of a file-backed data source in seconds",
    ["source"],
)
SOURCE_STALE = Gauge(
    "subnet_source_stale",
    "1 if a file-backed data source is stale",
    ["source"],
)
SYNC_RUNNING = Gauge("subnet_sync_running", "1 if freshness background sync is running")
SYNC_LAST_OK = Gauge("subnet_sync_last_ok", "1 if last freshness background sync succeeded")
SCHEDULER_RUNNING = Gauge(
    "subnet_scheduler_running",
    "1 if a background scheduler is running",
    ["scheduler"],
)
SCHEDULER_LAST_OK = Gauge(
    "subnet_scheduler_last_ok",
    "1 if the scheduler last tick succeeded",
    ["scheduler"],
)
SCHEDULER_FAILURES = Gauge(
    "subnet_scheduler_failures",
    "Consecutive scheduler tick failures",
    ["scheduler"],
)
SCHEDULER_JOB_COUNT = Gauge(
    "subnet_scheduler_job_count",
    "APScheduler jobs currently registered",
)


def _set_optional(gauge: Gauge, value: Optional[float], labels: Optional[Dict[str, str]] = None) -> None:
    if value is None:
        return
    if labels:
        gauge.labels(**labels).set(value)
    else:
        gauge.set(value)


def refresh_from_state() -> None:
    """Populate gauges from existing state APIs (read-only, scrape-time only)."""
    try:
        from internal.live_subnets import live_data_freshness

        live = live_data_freshness()
        _set_optional(LIVE_AGE_SECONDS, live.get("age_seconds"))
        if live.get("stale") is not None:
            LIVE_STALE.set(1 if live.get("stale") else 0)
    except Exception:
        pass

    try:
        from internal.freshness import get_sync_state

        sync = get_sync_state()
        SYNC_RUNNING.set(1 if sync.get("background_running") else 0)
        last_ok = sync.get("last_sync_ok")
        if last_ok is not None:
            SYNC_LAST_OK.set(1 if last_ok else 0)
        freshness = sync.get("freshness") or {}
        for source in _SOURCES:
            info = freshness.get(source) or {}
            _set_optional(SOURCE_AGE_SECONDS, info.get("age_seconds"), {"source": source})
            if info.get("is_stale") is not None:
                SOURCE_STALE.labels(source=source).set(1 if info.get("is_stale") else 0)
    except Exception:
        pass

    for scheduler, getter in (
        ("resolver", _resolver_state),
        ("adversarial", _adversarial_state),
    ):
        try:
            info = getter()
            SCHEDULER_RUNNING.labels(scheduler=scheduler).set(1 if info.get("running") else 0)
            last_ok = info.get("last_run_ok")
            if last_ok is not None:
                SCHEDULER_LAST_OK.labels(scheduler=scheduler).set(1 if last_ok else 0)
            failures = info.get("consecutive_failures")
            if failures is not None:
                SCHEDULER_FAILURES.labels(scheduler=scheduler).set(failures)
        except Exception:
            pass

    try:
        from internal.job_scheduler import state as job_scheduler_state

        js = job_scheduler_state()
        SCHEDULER_RUNNING.labels(scheduler="apscheduler").set(1 if js.get("running") else 0)
        SCHEDULER_JOB_COUNT.set(js.get("job_count", 0))
    except Exception:
        pass


def _resolver_state() -> Dict[str, Any]:
    from internal.council.resolver_scheduler import get_prediction_resolver_scheduler_state

    return get_prediction_resolver_scheduler_state()


def _adversarial_state() -> Dict[str, Any]:
    from internal.scheduler import get_adversarial_scheduler_state

    return get_adversarial_scheduler_state()


async def metrics_endpoint(request: Request) -> Response:
    """Expose Prometheus text format; refresh gauges before scrape."""
    refresh_from_state()
    body = generate_latest()
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")
