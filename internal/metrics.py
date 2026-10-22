"""Prometheus gauges refreshed from existing freshness/scheduler state()."""

from __future__ import annotations

from typing import Any, Dict, Optional

from prometheus_client import Counter, Gauge, generate_latest
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
LIVE_REFRESH_COMPLETE = Gauge(
    "subnet_live_refresh_complete",
    "1 complete refresh, 0 partial, -1 when live_subnets cache file missing",
)
# ponytail: sentinel when no cache file (do not report green complete).
LIVE_REFRESH_COMPLETE_UNAVAILABLE = -1.0
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

UNIVERSE_EMERGENCY_TOTAL = Counter(
    "subnet_universe_emergency_total",
    "Times the registry emergency fallback defined the subnet universe",
    ["reason"],
)

SCORE_SNAPSHOT_COVERAGE_COMPLETE = Gauge(
    "subnet_score_snapshot_coverage_complete",
    "1 if the last score snapshot cycle reported complete coverage",
)
SCORE_SNAPSHOT_COVERAGE_PUBLISHED = Gauge(
    "subnet_score_snapshot_coverage_published",
    "1 if the last score snapshot cycle published to disk",
)
SCORE_SNAPSHOT_TIMING_BUILD_SECONDS = Gauge(
    "subnet_score_snapshot_build_wall_seconds",
    "Wall seconds for the last score snapshot scoring build (-1 when unavailable)",
)
SCORE_SNAPSHOT_TIMING_BUILD_UNAVAILABLE = -1.0
SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS = Gauge(
    "subnet_score_snapshot_publish_wall_seconds",
    (
        "Publish wall seconds from coverage.timing.previous_publish_wall_seconds on "
        "disk (one cycle behind the writer). Process-local sample used immediately "
        "after a write in the same process. -1 when never observed or after restart "
        "until the next snapshot cycle."
    ),
)
SCORE_SNAPSHOT_TIMING_PUBLISH_UNAVAILABLE = -1.0
SCORE_SNAPSHOT_HORIZON_SUCCEEDED = Gauge(
    "subnet_score_snapshot_horizon_succeeded",
    "Independently scored netuids in the last coverage block (hour=0 when copied)",
    ["horizon"],
)
SCORE_SNAPSHOT_HORIZON_COPIED = Gauge(
    "subnet_score_snapshot_horizon_copied",
    "Rows covered by copy-from-day (not independent hour scoring)",
    ["horizon"],
)
SCORE_SNAPSHOT_AGE_SECONDS = Gauge(
    "subnet_score_snapshot_age_seconds",
    "Age of the served score snapshot (volume or seed) in seconds (-1 when none)",
)
# ponytail: sentinel for missing/unreadable snapshot file (always set gauge; never skip).
SCORE_SNAPSHOT_AGE_UNAVAILABLE = -1.0
SCORE_SNAPSHOT_SERVED_STATE = Gauge(
    "subnet_score_snapshot_served_state",
    "One-hot label for the snapshot state pick readers serve",
    ["state"],
)
SCORE_SNAPSHOT_LAST_CYCLE_COMPLETE = Gauge(
    "subnet_score_snapshot_last_cycle_complete",
    "1 if the last producer cycle receipt reported complete coverage",
)

READINESS_REPORT_AGE_SECONDS = Gauge(
    "readiness_report_age_seconds",
    "Age of the last stored /api/ops/readiness payload in seconds (-1 when never built)",
)
READINESS_LAST_SUCCESS_UNIX = Gauge(
    "readiness_last_success_build_unixtime",
    "Unix time of the last successful readiness cache store (0 when never built)",
)
READINESS_BUILDS_TOTAL = Counter(
    "readiness_builds_total",
    "Successful readiness report builds stored to cache",
)
READINESS_BUILD_FAILURES = Counter(
    "readiness_build_failures_total",
    "Readiness background or forced build failures",
    ["reason"],
)
READINESS_REPORT_AGE_UNAVAILABLE = -1.0

STAKE_ALERT_LAST_OK_AGE_SECONDS = Gauge(
    "stake_alert_last_ok_age_seconds",
    "Seconds since the validator stake alert watcher last completed a scan (-1 when unknown)",
)

DATA_VOLUME_FREE_BYTES = Gauge(
    "data_volume_free_bytes",
    "Free bytes on DATA_DIR volume",
)
DATA_VOLUME_USED_BYTES = Gauge(
    "data_volume_used_bytes",
    "Used bytes on DATA_DIR volume",
)
DATA_VOLUME_TOTAL_BYTES = Gauge(
    "data_volume_total_bytes",
    "Total bytes on DATA_DIR volume",
)
DATA_VOLUME_METRICS_OK = Gauge(
    "data_volume_metrics_ok",
    "1 when data_volume byte gauges were refreshed successfully",
)
# ponytail: sentinel when usage probe failed (do not leave last scrape values).
DATA_VOLUME_BYTES_UNAVAILABLE = -1.0
CHAIN_PRICE_SKIPPED_TOTAL = Counter(
    "chain_price_skipped_total",
    "Chain price forward recorder ticks skipped without sampling",
    ["reason"],
)
CHAIN_RPC_REQUESTS_TOTAL = Counter(
    "chain_rpc_requests_total",
    "Chain JSON-RPC requests by endpoint, method, and outcome",
    ["endpoint", "method", "outcome"],
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
        if not live.get("cache_present"):
            LIVE_REFRESH_COMPLETE.set(LIVE_REFRESH_COMPLETE_UNAVAILABLE)
        else:
            refresh_complete = live.get("refresh_complete")
            if refresh_complete is None:
                LIVE_REFRESH_COMPLETE.set(1.0)
            else:
                LIVE_REFRESH_COMPLETE.set(1.0 if refresh_complete else 0.0)
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

    try:
        _refresh_score_snapshot_gauges()
    except Exception:
        pass

    try:
        from internal.ops.readiness_cache import readiness_report_age_seconds

        age = readiness_report_age_seconds()
        READINESS_REPORT_AGE_SECONDS.set(
            age if age is not None else READINESS_REPORT_AGE_UNAVAILABLE
        )
    except Exception:
        pass

    try:
        from internal.message_intel.stake_alert import build_stake_alert_ops_summary

        stake = build_stake_alert_ops_summary()
        age = stake.get("last_ok_age_seconds")
        if age is None:
            STAKE_ALERT_LAST_OK_AGE_SECONDS.set(-1.0)
        else:
            STAKE_ALERT_LAST_OK_AGE_SECONDS.set(float(age))
    except Exception:
        pass

    try:
        from internal.disk_guard import disk_usage_for_metrics

        usage = disk_usage_for_metrics()
        if usage is None:
            DATA_VOLUME_FREE_BYTES.set(DATA_VOLUME_BYTES_UNAVAILABLE)
            DATA_VOLUME_USED_BYTES.set(DATA_VOLUME_BYTES_UNAVAILABLE)
            DATA_VOLUME_TOTAL_BYTES.set(DATA_VOLUME_BYTES_UNAVAILABLE)
            DATA_VOLUME_METRICS_OK.set(0)
        else:
            DATA_VOLUME_FREE_BYTES.set(usage.free)
            DATA_VOLUME_USED_BYTES.set(usage.used)
            DATA_VOLUME_TOTAL_BYTES.set(usage.total)
            DATA_VOLUME_METRICS_OK.set(1)
    except Exception:
        DATA_VOLUME_FREE_BYTES.set(DATA_VOLUME_BYTES_UNAVAILABLE)
        DATA_VOLUME_USED_BYTES.set(DATA_VOLUME_BYTES_UNAVAILABLE)
        DATA_VOLUME_TOTAL_BYTES.set(DATA_VOLUME_BYTES_UNAVAILABLE)
        DATA_VOLUME_METRICS_OK.set(0)


def _set_score_snapshot_age_gauge(age: Optional[float]) -> None:
    value = age if age is not None else SCORE_SNAPSHOT_AGE_UNAVAILABLE
    SCORE_SNAPSHOT_AGE_SECONDS.set(value)


def _refresh_score_snapshot_gauges() -> None:
    """Recompute snapshot coverage gauges from disk each scrape (no sticky greens)."""
    import json

    from internal.council.score_snapshots import (
        SCORE_SNAPSHOT_MAX_AGE_SECONDS,
        _score_snapshot_cycle_path,
        read_served_snapshot,
        snapshot_age_seconds,
    )
    from internal.council.snapshot_coverage import (
        clear_last_coverage_snapshot,
        publish_metrics,
        reset_score_snapshot_gauges,
    )

    age = snapshot_age_seconds()
    _set_score_snapshot_age_gauge(age)
    served = read_served_snapshot()
    for state in ("fresh", "aged", "seed", "none"):
        SCORE_SNAPSHOT_SERVED_STATE.labels(state=state).set(
            1.0 if served.state.value == state else 0.0
        )
    cycle_complete = 0.0
    try:
        with open(_score_snapshot_cycle_path(), "r", encoding="utf-8") as handle:
            cycle = json.load(handle)
        if isinstance(cycle, dict) and cycle.get("complete") is True:
            cycle_complete = 1.0
    except Exception:
        cycle_complete = 0.0
    SCORE_SNAPSHOT_LAST_CYCLE_COMPLETE.set(cycle_complete)

    disk_fresh = age is not None and age <= SCORE_SNAPSHOT_MAX_AGE_SECONDS
    if not disk_fresh:
        reset_score_snapshot_gauges()
        clear_last_coverage_snapshot()
        return
    snap = served.snapshot if served.servable else None
    disk_cov = snap.get("coverage") if isinstance(snap, dict) else None
    if not isinstance(disk_cov, dict) or not disk_cov:
        reset_score_snapshot_gauges()
        clear_last_coverage_snapshot()
        return
    publish_metrics(disk_cov)


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


