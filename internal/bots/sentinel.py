"""Read-only Sentinel health observer.

Composes existing health/freshness/ops signals into an immutable HealthReport.
Does not mutate application state, caches, workers, deployments, or artifacts.

Standing spec: ten predicates, each classified healthy / unhealthy / UNKNOWN,
with Policy §2.2 freshness (age, confidence, last_updated, source) on every
report and finding. Observations only — notify/evidence logging of the report
is the only allowed side effect.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from internal.ops.bot_policy import (
    FRESHNESS_THRESHOLDS,
    aggregate_freshness,
    bot_contract,
    classify_freshness,
)
from internal.ops.evidence import build_evidence_report
from internal.ops.notify import log_event, log_status, log_status

BOT_NAME = "sentinel"
PREDICATE_NAMES: Tuple[str, ...] = (
    "api_health",
    "latency",
    "worker",
    "resolver",
    "watchdog",
    "feed_sync",
    "cache_age",
    "scheduler",
    "learning",
    "deployment",
)

STATUS_HEALTHY = "healthy"
STATUS_UNHEALTHY = "unhealthy"
STATUS_UNKNOWN = "UNKNOWN"
FINDING_STATUSES: Tuple[str, ...] = (STATUS_HEALTHY, STATUS_UNHEALTHY, STATUS_UNKNOWN)

# Live-handler budget from internal/health/routes.py (same env default).
_LIVE_TIMEOUT_MS = float(os.environ.get("OPS_LIVE_HANDLER_TIMEOUT_SECONDS", "8")) * 1000.0

_STATUS_RANK = {STATUS_HEALTHY: 0, STATUS_UNKNOWN: 1, STATUS_UNHEALTHY: 2}

# Freshness-bucket confidence only — never a health-score. missing/degraded stay None.
_FRESHNESS_CONFIDENCE = {"fresh": 1.0, "aging": 0.5, "stale": 0.25}
_FRESHNESS_ORDER = {"fresh": 0, "aging": 1, "stale": 2, "missing": 3, "degraded": 4}


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _freeze(value: Any) -> Any:
    if isinstance(value, MappingProxyType):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _safe(label: str, fn: Callable[[], Any], default: Any = None) -> Any:
    try:
        return fn()
    except Exception as exc:
        fallback: Dict[str, Any] = {"_error": f"{label}: {exc}"}
        if isinstance(default, dict):
            fallback.update(default)
        elif default is not None:
            return default
        return fallback


@dataclass(frozen=True)
class PredicateResult:
    """One health predicate outcome. Frozen after construction."""

    name: str
    status: str
    detail: str
    freshness: Mapping[str, Any]
    evidence: Mapping[str, Any]
    metrics: Mapping[str, Any]
    reason: Optional[str]


@dataclass(frozen=True)
class HealthReport:
    """Immutable Sentinel observation. Values only — never an accumulator."""

    bot: str
    run_id: str
    checked_at: str
    status: str
    summary: str
    predicates: Tuple[PredicateResult, ...]
    freshness: Mapping[str, Any]
    confidence: Optional[float]
    approval: Mapping[str, Any]
    approval_required: bool
    evidence: Mapping[str, Any]
    unknowns: Tuple[str, ...]
    recommended_action: Optional[str]
    audit: Mapping[str, Any]


def _read_predictions_readonly() -> Dict[str, Any]:
    """json.load only — skips predictions_store migrations that call save_predictions."""
    from internal.learning.predictions_store import PREDICTIONS_PATH, _default_data

    try:
        with open(PREDICTIONS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else _default_data()
    except Exception:
        return _default_data()


def _live_cache_freshness() -> Dict[str, Any]:
    """Read data/live_subnets.json only. Does not call probe_feed_layers/init_db."""
    from internal.live_subnets import MAX_STALE_SECONDS, _cache_path

    info: Dict[str, Any] = {
        "last_sync": None,
        "age_seconds": None,
        "subnet_count": 0,
        "stale": True,
        "cache_path": _cache_path(),
    }
    path = _cache_path()
    if not os.path.isfile(path):
        return info
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return info
    info["last_sync"] = data.get("synced_at")
    try:
        info["subnet_count"] = int(data.get("count") or len(data.get("subnets") or []) or 0)
    except (TypeError, ValueError):
        info["subnet_count"] = 0
    if data.get("synced_at"):
        try:
            parsed = datetime.fromisoformat(str(data["synced_at"]).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
            info["age_seconds"] = int(age)
            info["stale"] = age > MAX_STALE_SECONDS
        except (TypeError, ValueError, OverflowError):
            pass
    if info["subnet_count"] > 0:
        info["effective_source"] = "blockmachine"
        info["effective_total"] = info["subnet_count"]
    else:
        info["effective_source"] = None
        info["effective_total"] = 0
    return info


_EVIDENCE_LOCK = threading.Lock()


def _evidence_readonly() -> Dict[str, Any]:
    # ponytail: capture telemetry calls load_predictions, which can migrate and
    # write predictions.json. Swap in a json.load-only loader for this call.
    # Upgrade: add read_only=True on load_predictions / build_evidence_report.
    import internal.learning.predictions_store as pred_store

    with _EVIDENCE_LOCK:
        saved = pred_store.load_predictions
        pred_store.load_predictions = _read_predictions_readonly
        try:
            return build_evidence_report()
        finally:
            pred_store.load_predictions = saved


def collect_snapshot() -> Dict[str, Any]:
    """Read current signals. File and in-process reads only; no writers."""
    started = time.perf_counter()

    def _liveness() -> Dict[str, Any]:
        from internal.ops.readiness import build_liveness_report

        return build_liveness_report(probe_worker=False)

    liveness = _safe("liveness", _liveness)
    latency_ms = round((time.perf_counter() - started) * 1000.0, 1)

    def _loop_health() -> Dict[str, Any]:
        from internal.learning.loop_health import build_learning_loop_health
        from internal.learning.predictions_store import PREDICTIONS_PATH

        return build_learning_loop_health(predictions_path=PREDICTIONS_PATH)

    def _resolver() -> Dict[str, Any]:
        from internal.council.resolver_scheduler import get_prediction_resolver_scheduler_state

        return get_prediction_resolver_scheduler_state()

    def _sync() -> Dict[str, Any]:
        from internal.freshness import get_sync_state

        return get_sync_state()

    def _jobs() -> Dict[str, Any]:
        from internal.job_scheduler import state as job_scheduler_state

        return job_scheduler_state()

    def _pump() -> Dict[str, Any]:
        from internal.pump.scheduler import get_pump_ladder_scheduler_state

        return get_pump_ladder_scheduler_state()

    loop_health = _safe("loop_health", _loop_health)
    resolver = _safe("resolver", _resolver)
    live = _safe("live", _live_cache_freshness)
    sync = _safe("sync", _sync)
    file_freshness = sync.get("freshness") if isinstance(sync, dict) else None
    if not isinstance(file_freshness, dict):
        def _files() -> Dict[str, Any]:
            from internal.freshness import overall_freshness

            return overall_freshness()

        file_freshness = _safe("file_freshness", _files)
    job_scheduler = _safe("job_scheduler", _jobs)
    pump_scheduler = _safe("pump_scheduler", _pump)
    evidence = _safe("evidence", _evidence_readonly)
    feed = {
        "effective_source": live.get("effective_source") if isinstance(live, dict) else None,
        "likely_total": (live.get("effective_total") if isinstance(live, dict) else None)
        or (live.get("subnet_count") if isinstance(live, dict) else 0),
        "live_cache": {
            "synced_at": live.get("last_sync") if isinstance(live, dict) else None,
            "count": live.get("subnet_count") if isinstance(live, dict) else 0,
            "stale": live.get("stale") if isinstance(live, dict) else True,
        },
        "_error": live.get("_error") if isinstance(live, dict) else None,
    }
    feed = {key: value for key, value in feed.items() if key != "_error" or value}

    def _snapshot_guard() -> Dict[str, Any]:
        from internal import snapshot_guard

        return {
            "installed": snapshot_guard._ORIG is not None,
            "cold": bool(snapshot_guard._LAST_GOOD.get("cold")),
        }

    watchdog = None
    if isinstance(loop_health, dict):
        watchdog = loop_health.get("watchdog")
    worker_peer = None
    if isinstance(liveness, dict):
        worker_peer = liveness.get("worker_peer")
    if not isinstance(worker_peer, dict) and isinstance(loop_health, dict):
        worker_peer = loop_health.get("worker_peer")

    return {
        "checked_at": _utcnow_z(),
        "latency_ms": latency_ms,
        "liveness": liveness if isinstance(liveness, dict) else {"_error": "liveness"},
        "loop_health": loop_health if isinstance(loop_health, dict) else {"_error": "loop_health"},
        "resolver": resolver if isinstance(resolver, dict) else {"_error": "resolver"},
        "feed": feed if isinstance(feed, dict) else {"_error": "feed"},
        "live": live if isinstance(live, dict) else {"_error": "live"},
        "sync": sync if isinstance(sync, dict) else {"_error": "sync"},
        "file_freshness": file_freshness if isinstance(file_freshness, dict) else {},
        "job_scheduler": job_scheduler if isinstance(job_scheduler, dict) else {},
        "pump_scheduler": pump_scheduler if isinstance(pump_scheduler, dict) else {},
        "evidence": evidence if isinstance(evidence, dict) else {},
        "snapshot_guard": _safe("snapshot_guard", _snapshot_guard, {"installed": False}),
        "watchdog": watchdog if isinstance(watchdog, dict) else {},
        "worker_peer": worker_peer if isinstance(worker_peer, dict) else {},
    }


def _envelope(
    source: str,
    captured_at: Any,
    *,
    degraded: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    return classify_freshness(source, captured_at, now=now, degraded=degraded)


def _policy_freshness(envelope: Mapping[str, Any]) -> Dict[str, Any]:
    """Policy §2.2 envelope plus standing-spec aliases: age, confidence, last_updated, source."""
    env = dict(envelope)
    nested = env.get("sources")
    if isinstance(nested, list):
        env["sources"] = [
            _policy_freshness(item) if isinstance(item, Mapping) else item for item in nested
        ]
    age = env.get("age_seconds")
    last_updated = env.get("captured_at") or env.get("observed_at")
    source = env.get("source")
    if not source:
        items = [item for item in (env.get("sources") or []) if isinstance(item, Mapping)]
        if items:
            worst = max(
                items,
                key=lambda item: _FRESHNESS_ORDER.get(str(item.get("status")), 4),
            )
            source = worst.get("source")
    env["age"] = age
    env["confidence"] = _FRESHNESS_CONFIDENCE.get(str(env.get("status") or ""))
    env["last_updated"] = last_updated
    env["source"] = source
    return env


def _finding(
    name: str,
    status: str,
    detail: str,
    freshness: Mapping[str, Any],
    metrics: Optional[Mapping[str, Any]] = None,
    *,
    reason: Optional[str] = None,
) -> PredicateResult:
    frozen_metrics = _freeze(metrics or {})
    if status == STATUS_UNKNOWN:
        reason = str(reason or detail)
    return PredicateResult(
        name=name,
        status=status,
        detail=detail,
        freshness=_freeze(_policy_freshness(freshness)),
        evidence=frozen_metrics,
        metrics=frozen_metrics,
        reason=reason,
    )


def _has_error(payload: Any) -> bool:
    return isinstance(payload, dict) and bool(payload.get("_error"))


def _usable(payload: Any) -> bool:
    return isinstance(payload, dict) and bool(payload) and not _has_error(payload)


def _api_health(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    live = snapshot.get("liveness") or {}
    if not live or _has_error(live):
        reason = live.get("_error") if isinstance(live, dict) else "liveness signal missing"
        return _finding(
            "api_health",
            STATUS_UNKNOWN,
            str(reason or "liveness signal missing"),
            _envelope("learning_health", None, now=now),
            {"liveness": live} if isinstance(live, dict) else {},
            reason=str(reason or "liveness signal missing"),
        )
    volume = live.get("volume") if isinstance(live.get("volume"), dict) else {}
    ok = bool(live.get("live")) and str(live.get("status") or "").lower() in ("ok", "degraded")
    metrics = {"status": live.get("status"), "live": live.get("live"), "volume": volume}
    if not ok:
        return _finding(
            "api_health",
            STATUS_UNHEALTHY,
            f"liveness status={live.get('status')} live={live.get('live')}",
            _envelope("learning_health", None, now=now),
            metrics,
        )
    if str(live.get("status")).lower() == "degraded" or volume.get("writable") is False:
        return _finding(
            "api_health",
            STATUS_UNHEALTHY,
            f"process live; volume writable={volume.get('writable')}",
            _envelope("learning_health", None, now=now),
            metrics,
        )
    return _finding(
        "api_health",
        STATUS_HEALTHY,
        "liveness report ok",
        _envelope("learning_health", None, now=now),
        metrics,
    )


def _latency(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    ms = snapshot.get("latency_ms")
    if ms is None:
        return _finding(
            "latency",
            STATUS_UNKNOWN,
            "no in-process health-path timing",
            _envelope("learning_health", None, now=now),
            {},
            reason="no in-process health-path timing",
        )
    try:
        value = float(ms)
    except (TypeError, ValueError):
        return _finding(
            "latency",
            STATUS_UNKNOWN,
            f"unreadable latency_ms={ms!r}",
            _envelope("learning_health", None, now=now, degraded=True),
            {"latency_ms": ms},
            reason=f"unreadable latency_ms={ms!r}",
        )
    timeout_ms = _LIVE_TIMEOUT_MS
    metrics = {"latency_ms": value, "budget_ms": timeout_ms}
    if value <= timeout_ms:
        return _finding(
            "latency",
            STATUS_HEALTHY,
            f"liveness path {value:.1f}ms (budget {timeout_ms:.0f}ms OPS_LIVE_HANDLER_TIMEOUT)",
            _envelope("learning_health", None, now=now),
            metrics,
        )
    return _finding(
        "latency",
        STATUS_UNHEALTHY,
        f"liveness path {value:.1f}ms exceeded {timeout_ms:.0f}ms live-handler budget",
        _envelope("learning_health", None, now=now),
        metrics,
    )


def _worker(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    peer = snapshot.get("worker_peer") or {}
    if not peer or _has_error(peer):
        return _finding(
            "worker",
            STATUS_UNKNOWN,
            "worker_peer signal missing",
            _envelope("worker_heartbeat", None, now=now),
            {"worker_peer": peer} if isinstance(peer, dict) else {},
            reason="worker_peer signal missing",
        )
    heartbeat = peer.get("heartbeat") if isinstance(peer.get("heartbeat"), dict) else {}
    ts = heartbeat.get("ts")
    metrics = {"alive": peer.get("alive"), "expected": peer.get("expected"), "peer": peer.get("peer")}
    freshness = _envelope(
        "worker_heartbeat",
        ts,
        now=now,
        degraded=peer.get("alive") is False,
    )
    if peer.get("expected") is False:
        return _finding(
            "worker",
            STATUS_HEALTHY,
            "worker not required in this process",
            freshness,
            metrics,
        )
    if peer.get("alive") is True:
        return _finding(
            "worker",
            STATUS_HEALTHY,
            f"peer={peer.get('peer')} source={peer.get('source')}",
            freshness,
            metrics,
        )
    if peer.get("alive") is False:
        return _finding(
            "worker",
            STATUS_UNHEALTHY,
            peer.get("note") or "worker peer not alive",
            freshness,
            metrics,
        )
    return _finding(
        "worker",
        STATUS_UNKNOWN,
        "worker liveness deferred (no HTTP probe)",
        freshness,
        metrics,
        reason="worker liveness deferred (no HTTP probe)",
    )


def _resolver(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    loop = snapshot.get("loop_health") or {}
    loop_resolver = loop.get("resolver") if isinstance(loop.get("resolver"), dict) else {}
    resolver = snapshot.get("resolver") or {}
    if (_has_error(loop) and _has_error(resolver)) or (not loop_resolver and not resolver):
        return _finding(
            "resolver",
            STATUS_UNKNOWN,
            "resolver scheduler state missing",
            _envelope("resolver", None, now=now),
            {},
            reason="resolver scheduler state missing",
        )
    running = loop_resolver.get("running")
    if running is None:
        running = resolver.get("running")
    last_ok = loop_resolver.get("last_ok")
    if last_ok is None:
        last_ok = resolver.get("last_run_ok")
    last_at = (
        loop.get("last_resolver_tick")
        or resolver.get("last_run_at")
        or loop_resolver.get("last_run_at")
    )
    try:
        failures = int(resolver.get("consecutive_failures") or 0)
    except (TypeError, ValueError):
        return _finding(
            "resolver",
            STATUS_UNKNOWN,
            f"unreadable consecutive_failures={resolver.get('consecutive_failures')!r}",
            _envelope("resolver", last_at, now=now),
            {"consecutive_failures": resolver.get("consecutive_failures")},
            reason=f"unreadable consecutive_failures={resolver.get('consecutive_failures')!r}",
        )
    lifecycle = loop_resolver.get("lifecycle") or resolver.get("lifecycle")
    metrics = {
        "running": running,
        "last_ok": last_ok,
        "lifecycle": lifecycle,
        "consecutive_failures": failures,
    }
    if failures > 0 or last_ok is False:
        status = STATUS_UNHEALTHY
        detail = f"last_ok={last_ok} consecutive_failures={failures}"
    elif loop_resolver.get("warming") or lifecycle in {"starting", "scheduled"}:
        status = STATUS_UNHEALTHY
        detail = f"lifecycle={lifecycle} warming={loop_resolver.get('warming')}"
    elif running is True and last_at:
        status = STATUS_HEALTHY
        detail = f"running lifecycle={lifecycle}"
    elif running is True:
        status = STATUS_UNKNOWN
        detail = "resolver marked running but no last tick"
    elif running is False:
        status = STATUS_UNHEALTHY
        detail = "resolver not running"
    else:
        status = STATUS_UNKNOWN
        detail = "resolver running flag absent"
    return _finding(
        "resolver",
        status,
        detail,
        _envelope(
            "resolver",
            last_at,
            now=now,
            degraded=status == STATUS_UNHEALTHY and last_ok is False,
        ),
        metrics,
        reason=detail if status == STATUS_UNKNOWN else None,
    )


def _watchdog(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    loop = snapshot.get("loop_health") or {}
    watchdog = snapshot.get("watchdog") or loop.get("watchdog") or {}
    captured = loop.get("last_resolver_tick")
    metrics = watchdog if isinstance(watchdog, dict) else {}
    if not watchdog or "warning" not in watchdog:
        return _finding(
            "watchdog",
            STATUS_UNKNOWN,
            "resolver watchdog payload missing",
            _envelope("resolver", None, now=now),
            metrics,
            reason="resolver watchdog payload missing",
        )
    warning = bool(watchdog.get("warning"))
    detail = watchdog.get("reason") or f"warning={warning} pending={watchdog.get('pending_count')}"
    return _finding(
        "watchdog",
        STATUS_UNHEALTHY if warning else STATUS_HEALTHY,
        str(detail),
        _envelope("resolver", captured, now=now, degraded=warning),
        metrics,
    )


def _feed_sync(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    feed = snapshot.get("feed") or {}
    live = snapshot.get("live") or {}
    sync = snapshot.get("sync") or {}
    if _has_error(feed) and _has_error(live):
        reason = feed.get("_error") or live.get("_error") or "feed signals missing"
        return _finding(
            "feed_sync",
            STATUS_UNKNOWN,
            str(reason),
            _envelope("live_feed", None, now=now),
            {},
            reason=str(reason),
        )
    live_cache = feed.get("live_cache") if isinstance(feed.get("live_cache"), dict) else {}
    captured = (
        live_cache.get("synced_at")
        or live.get("last_sync")
        or sync.get("last_sync_at")
    )
    effective = feed.get("effective_source")
    try:
        likely = int(feed.get("likely_total") or 0)
    except (TypeError, ValueError):
        return _finding(
            "feed_sync",
            STATUS_UNKNOWN,
            f"unreadable likely_total={feed.get('likely_total')!r}",
            _envelope("live_feed", captured, now=now),
            {"likely_total": feed.get("likely_total")},
            reason=f"unreadable likely_total={feed.get('likely_total')!r}",
        )
    degraded = effective in (None, "none") or _has_error(feed)
    metrics = {
        "effective_source": effective,
        "likely_total": likely,
        "stale": live.get("stale"),
        "last_sync_ok": sync.get("last_sync_ok"),
    }
    if degraded:
        if effective == "none":
            status = STATUS_UNHEALTHY
            detail = f"effective_source={effective} likely_total={likely}"
            reason = None
        else:
            status = STATUS_UNKNOWN
            detail = f"effective_source={effective} likely_total={likely}"
            reason = "live feed effective_source missing"
    elif effective == "registry":
        status = STATUS_UNHEALTHY
        detail = "subnet feed registry-only"
        reason = None
    elif live.get("stale") and int(live.get("subnet_count") or 0) == 0 and likely <= 0:
        status = STATUS_UNHEALTHY
        detail = "live cache empty and stale"
        reason = None
    elif sync.get("last_sync_ok") is False:
        status = STATUS_UNHEALTHY
        detail = "freshness background sync last_sync_ok=false"
        reason = None
    else:
        status = STATUS_HEALTHY
        detail = f"effective_source={effective} likely_total={likely}"
        reason = None
    return _finding(
        "feed_sync",
        status,
        detail,
        _envelope("live_feed", captured, now=now, degraded=degraded),
        metrics,
        reason=reason,
    )


def _cache_age(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    files = snapshot.get("file_freshness") or {}
    live = snapshot.get("live") or {}
    loop = snapshot.get("loop_health") or {}
    overall = files.get("overall") if isinstance(files.get("overall"), dict) else {}
    price = files.get("price_cache") if isinstance(files.get("price_cache"), dict) else {}
    captured = price.get("last_updated") or live.get("last_sync")
    snap_age = loop.get("snapshot_age_seconds")
    has_file_flag = "any_stale" in overall
    has_live_flag = "stale" in live
    if not has_file_flag and not has_live_flag and snap_age is None:
        return _finding(
            "cache_age",
            STATUS_UNKNOWN,
            "file freshness snapshot missing",
            _envelope("market_data", None, now=now),
            {},
            reason="file freshness snapshot missing",
        )
    stale_flags = []
    if overall.get("any_stale"):
        stale_flags.append("file_sources")
    if live.get("stale"):
        stale_flags.append("live_cache")
    if isinstance(snap_age, (int, float)) and snap_age > 2700:
        stale_flags.append("score_snapshot")
    metrics = {
        "any_stale": overall.get("any_stale"),
        "live_age_seconds": live.get("age_seconds"),
        "snapshot_age_seconds": snap_age,
    }
    if stale_flags:
        return _finding(
            "cache_age",
            STATUS_UNHEALTHY,
            "stale: " + ",".join(stale_flags),
            _envelope("market_data", captured, now=now, degraded=not captured),
            metrics,
        )
    return _finding(
        "cache_age",
        STATUS_HEALTHY,
        f"any_stale={overall.get('any_stale')} live_age={live.get('age_seconds')}",
        _envelope("market_data", captured, now=now),
        metrics,
    )


def _scheduler(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    jobs = snapshot.get("job_scheduler") or {}
    pump = snapshot.get("pump_scheduler") or {}
    resolver = snapshot.get("resolver") or {}
    loop = snapshot.get("loop_health") or {}
    pick = loop.get("pick_scheduler") if isinstance(loop.get("pick_scheduler"), dict) else {}
    try:
        failures = dict(jobs.get("last_failures") or {})
    except (TypeError, ValueError):
        return _finding(
            "scheduler",
            STATUS_UNKNOWN,
            f"unreadable last_failures={jobs.get('last_failures')!r}",
            _envelope("resolver", None, now=now),
            {"last_failures": jobs.get("last_failures") if isinstance(jobs, dict) else None},
            reason=f"unreadable last_failures={jobs.get('last_failures')!r}",
        )
    failed: list[str] = list(failures.keys())
    try:
        resolver_failures = int(resolver.get("consecutive_failures") or 0)
    except (TypeError, ValueError):
        resolver_failures = None
    if resolver_failures:
        failed.append("resolver")
    if resolver.get("last_run_ok") is False:
        failed.append("resolver_last_run")
    daily = pick.get("daily") if isinstance(pick.get("daily"), dict) else {}
    hour = pick.get("hour") if isinstance(pick.get("hour"), dict) else {}
    if daily.get("last_run_ok") is False:
        failed.append("daily_pick")
    if hour.get("last_run_ok") is False:
        failed.append("hour_pick")
    if pump.get("last_run_ok") is False:
        failed.append("pump_ladder")
    captured = (
        daily.get("last_run_at")
        or pump.get("last_run_at")
        or resolver.get("last_run_at")
        or loop.get("last_resolver_tick")
    )
    saw_any = _usable(jobs) or bool(pick) or _usable(pump) or _usable(resolver)
    metrics = {"last_failures": failures, "failed": failed, "running": jobs.get("running")}
    if failed:
        return _finding(
            "scheduler",
            STATUS_UNHEALTHY,
            "failures: " + ",".join(failed),
            _envelope("resolver", captured, now=now, degraded=True),
            metrics,
        )
    if not saw_any:
        return _finding(
            "scheduler",
            STATUS_UNKNOWN,
            "no scheduler state in this process",
            _envelope("resolver", captured, now=now),
            metrics,
            reason="no scheduler state in this process",
        )
    if jobs.get("running") is False and not captured:
        return _finding(
            "scheduler",
            STATUS_UNKNOWN,
            "background scheduler not running in this process",
            _envelope("resolver", captured, now=now),
            metrics,
            reason="background scheduler not running in this process",
        )
    return _finding(
        "scheduler",
        STATUS_HEALTHY,
        f"apscheduler running={jobs.get('running')} jobs={jobs.get('job_count')}",
        _envelope("resolver", captured, now=now),
        metrics,
    )


def _learning(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    loop = snapshot.get("loop_health") or {}
    evidence = snapshot.get("evidence") or {}
    if not loop or _has_error(loop):
        reason = loop.get("_error") if isinstance(loop, dict) else "learning health missing"
        return _finding(
            "learning",
            STATUS_UNKNOWN,
            str(reason or "learning health missing"),
            _envelope("learning_health", None, now=now),
            {},
            reason=str(reason or "learning health missing"),
        )
    status_raw = str(loop.get("status") or "").lower()
    captured = loop.get("checked_at")
    alerts = list(evidence.get("alerts") or [])
    council = ((evidence.get("learning_outcomes") or {}) if isinstance(evidence, dict) else {})
    council_health = (council.get("council_health") or {}) if isinstance(council, dict) else {}
    metrics = {
        "status": loop.get("status"),
        "pending": loop.get("pending"),
        "ledger": loop.get("ledger"),
        "alerts": alerts,
    }
    if status_raw == "stalled" or "council_health ALERT" in alerts:
        status = STATUS_UNHEALTHY
        detail = f"loop_health={status_raw} alerts={alerts[:3]}"
        reason = None
    elif status_raw in {"degraded", "warming"} or str(council_health.get("escalation") or "") == "WATCH":
        status = STATUS_UNHEALTHY
        detail = f"loop_health={status_raw} escalation={council_health.get('escalation')}"
        reason = None
    elif status_raw == "ok":
        status = STATUS_HEALTHY
        detail = f"loop_health=ok pending={loop.get('pending')}"
        reason = None
    else:
        status = STATUS_UNKNOWN
        detail = f"loop_health status={status_raw or 'missing'}"
        reason = f"loop_health status={status_raw or 'missing'}"
    return _finding(
        "learning",
        status,
        detail,
        _envelope(
            "learning_health",
            captured,
            now=now,
            degraded=status_raw in {"degraded", "stalled"} or status == STATUS_UNHEALTHY,
        ),
        metrics,
        reason=reason,
    )


def _deployment(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    guard = snapshot.get("snapshot_guard") or {}
    loop = snapshot.get("loop_health") or {}
    peer = snapshot.get("worker_peer") or {}
    captured = None
    if guard.get("installed") and guard.get("cold"):
        return _finding(
            "deployment",
            STATUS_UNHEALTHY,
            "learning snapshot guard serving cold fallback",
            _envelope("github", captured, now=now, degraded=True),
            {"signal": "snapshot_guard", **dict(guard)},
        )
    snap_age = loop.get("snapshot_age_seconds")
    worker_alive = peer.get("alive") is True
    if worker_alive and isinstance(snap_age, (int, float)) and snap_age > 2700:
        return _finding(
            "deployment",
            STATUS_UNHEALTHY,
            f"score snapshot age {snap_age:.0f}s while worker alive",
            _envelope("github", captured, now=now),
            {"signal": "score_snapshot", "snapshot_age_seconds": snap_age, "worker_alive": True},
        )
    return _finding(
        "deployment",
        STATUS_UNKNOWN,
        "no GitHub/CI revision timestamp in this process",
        _envelope("github", None, now=now),
        {"installed": bool(guard.get("installed")), "cold": guard.get("cold")},
        reason="no GitHub/CI revision timestamp in this process",
    )


_EVALUATORS: Tuple[Callable[[Mapping[str, Any], datetime], PredicateResult], ...] = (
    _api_health,
    _latency,
    _worker,
    _resolver,
    _watchdog,
    _feed_sync,
    _cache_age,
    _scheduler,
    _learning,
    _deployment,
)


def evaluate_predicates(
    snapshot: Mapping[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Tuple[PredicateResult, ...]:
    """Pure evaluation of the ten predicates against a collected snapshot."""
    reference = now or datetime.now(timezone.utc)
    results: list[PredicateResult] = []
    for fn in _EVALUATORS:
        name = fn.__name__[1:] if fn.__name__.startswith("_") else fn.__name__
        try:
            results.append(fn(snapshot, reference))
        except Exception as exc:
            results.append(
                _finding(
                    name,
                    STATUS_UNKNOWN,
                    f"predicate could not be evaluated: {exc}",
                    _envelope("learning_health", None, now=reference),
                    {},
                    reason=f"predicate could not be evaluated: {exc}",
                )
            )
    return tuple(results)


def _report_status(predicates: Tuple[PredicateResult, ...]) -> str:
    worst = STATUS_HEALTHY
    for item in predicates:
        if _STATUS_RANK.get(item.status, 1) > _STATUS_RANK.get(worst, 0):
            worst = item.status
    return worst


def _notify_level(status: str) -> str:
    if status == STATUS_UNHEALTHY:
        return "error"
    if status == STATUS_UNKNOWN:
        return "warning"
    return "info"


def _log_checks_and_findings(
    run_id: str,
    predicates: Tuple[PredicateResult, ...],
    *,
    status: str,
    summary: str,
    freshness: Mapping[str, Any],
) -> None:
    for item in predicates:
        log_event(
            "sentinel_predicate",
            message=item.detail,
            level=_notify_level(item.status),
            run_id=run_id,
            predicate=item.name,
            status=item.status,
            reason=item.reason,
        )
    log_status(
        summary,
        level=_notify_level(status),
        run_id=run_id,
        bot=BOT_NAME,
        status=status,
        freshness=freshness.get("status"),
    )
    log_event(
        "sentinel_health",
        summary=summary,
        level=_notify_level(status),
        run_id=run_id,
        status=status,
        freshness=freshness.get("status"),
    )
    log_event("bot_observe", message=f"sentinel {status}", level="info", run_id=run_id, bot=BOT_NAME)


def observe(*, snapshot: Optional[Mapping[str, Any]] = None) -> HealthReport:
    """Run a read-only health pass and return an immutable report."""
    started = time.perf_counter()
    run_id = uuid.uuid4().hex
    collected = dict(snapshot) if snapshot is not None else collect_snapshot()
    checked_at = str(collected.get("checked_at") or _utcnow_z())
    now = datetime.now(timezone.utc)
    predicates = evaluate_predicates(collected, now=now)
    unknowns = tuple(item.name for item in predicates if item.status == STATUS_UNKNOWN)
    freshness_sources: list[Dict[str, Any]] = []
    skip_aggregate = {"api_health", "latency", "deployment"}
    for item in predicates:
        if item.name in skip_aggregate:
            continue
        env = dict(item.freshness)
        if env.get("source") not in FRESHNESS_THRESHOLDS:
            continue
        if env.get("captured_at") is None and env.get("status") != "degraded":
            continue
        freshness_sources.append(env)
    evidence = collected.get("evidence") if isinstance(collected.get("evidence"), dict) else {}
    for extra in evidence.get("evidence_sources") or []:
        if not isinstance(extra, Mapping):
            continue
        if extra.get("source") not in FRESHNESS_THRESHOLDS:
            continue
        if extra.get("captured_at") is None and extra.get("status") != "degraded":
            continue
        freshness_sources.append(dict(extra))
    freshness = _policy_freshness(aggregate_freshness(freshness_sources))
    contract = bot_contract(freshness=freshness, state_changing=False)
    confidence = None
    status = _report_status(predicates)
    unhealthy = [item.name for item in predicates if item.status == STATUS_UNHEALTHY]
    if unhealthy:
        summary = "unhealthy: " + ", ".join(unhealthy)
    elif unknowns:
        summary = "unknown: " + ", ".join(unknowns)
    else:
        summary = "all ten health predicates healthy"
    _log_checks_and_findings(
        run_id,
        predicates,
        status=status,
        summary=summary,
        freshness=freshness,
    )
    report = HealthReport(
        bot=BOT_NAME,
        run_id=run_id,
        checked_at=checked_at,
        status=status,
        summary=summary,
        predicates=predicates,
        freshness=_freeze(freshness),
        confidence=confidence,
        approval=_freeze(contract["approval"]),
        approval_required=bool(contract["approval_required"]),
        evidence=_freeze(evidence),
        unknowns=unknowns,
        recommended_action=None,
        audit=_freeze(
            {
                "sources_read": [
                    "internal.ops.readiness.build_liveness_report",
                    "internal.learning.loop_health.build_learning_loop_health",
                    "internal.live_subnets live cache file",
                    "internal.ops.evidence.build_evidence_report",
                    "internal.freshness.get_sync_state",
                ],
                "duration_ms": round((time.perf_counter() - started) * 1000.0, 1),
                "state_changing": False,
            }
        ),
    )
    return report
