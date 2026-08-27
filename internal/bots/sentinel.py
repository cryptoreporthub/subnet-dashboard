"""Read-only Sentinel health observer.

Composes existing health/freshness/ops signals into an immutable HealthReport.
Does not mutate application state, caches, workers, deployments, or artifacts.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from internal.ops.bot_policy import aggregate_freshness, bot_contract, classify_freshness
from internal.ops.evidence import build_evidence_report
from internal.ops.notify import log_event

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

# Health-path latency: original Sentinel check used 500ms; /health SLA is <1s.
_LATENCY_OK_MS = 500.0
_LATENCY_WARN_MS = 1000.0

_STATUS_RANK = {"ok": 0, "warn": 1, "unknown": 2, "fail": 3}


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

        return build_learning_loop_health()

    def _resolver() -> Dict[str, Any]:
        from internal.council.resolver_scheduler import get_prediction_resolver_scheduler_state

        return get_prediction_resolver_scheduler_state()

    def _live() -> Dict[str, Any]:
        from internal.live_subnets import live_data_freshness

        return live_data_freshness()

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
    live = _safe("live", _live)
    sync = _safe("sync", _sync)
    file_freshness = sync.get("freshness") if isinstance(sync, dict) else None
    if not isinstance(file_freshness, dict):
        def _files() -> Dict[str, Any]:
            from internal.freshness import overall_freshness

            return overall_freshness()

        file_freshness = _safe("file_freshness", _files)
    job_scheduler = _safe("job_scheduler", _jobs)
    pump_scheduler = _safe("pump_scheduler", _pump)
    evidence = _safe("evidence", build_evidence_report)
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


def _has_error(payload: Any) -> bool:
    return isinstance(payload, dict) and bool(payload.get("_error"))


def _api_health(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    live = snapshot.get("liveness") or {}
    checked = live.get("checked_at") or snapshot.get("checked_at")
    if not live or _has_error(live):
        return PredicateResult(
            "api_health",
            "unknown",
            live.get("_error") if isinstance(live, dict) else "liveness signal missing",
            _envelope("learning_health", None, now=now),
            _freeze({"liveness": live}),
        )
    volume = live.get("volume") if isinstance(live.get("volume"), dict) else {}
    ok = bool(live.get("live")) and str(live.get("status") or "").lower() in ("ok", "degraded")
    if not ok:
        status = "fail"
        detail = f"liveness status={live.get('status')} live={live.get('live')}"
    elif str(live.get("status")).lower() == "degraded" or volume.get("writable") is False:
        status = "warn"
        detail = f"process live; volume writable={volume.get('writable')}"
    else:
        status = "ok"
        detail = "liveness report ok"
    return PredicateResult(
        "api_health",
        status,
        detail,
        _envelope("learning_health", checked, now=now, degraded=status == "fail"),
        _freeze({"status": live.get("status"), "live": live.get("live"), "volume": volume}),
    )


def _latency(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    ms = snapshot.get("latency_ms")
    checked = snapshot.get("checked_at")
    if ms is None:
        return PredicateResult(
            "latency",
            "unknown",
            "no in-process health-path timing",
            _envelope("learning_health", None, now=now),
            _freeze({}),
        )
    try:
        value = float(ms)
    except (TypeError, ValueError):
        return PredicateResult(
            "latency",
            "unknown",
            f"unreadable latency_ms={ms!r}",
            _envelope("learning_health", None, now=now, degraded=True),
            _freeze({"latency_ms": ms}),
        )
    if value <= _LATENCY_OK_MS:
        status = "ok"
    elif value <= _LATENCY_WARN_MS:
        status = "warn"
    else:
        status = "fail"
    return PredicateResult(
        "latency",
        status,
        f"liveness path {value:.1f}ms (ok<={_LATENCY_OK_MS:.0f} warn<={_LATENCY_WARN_MS:.0f})",
        _envelope("learning_health", checked, now=now, degraded=status == "fail"),
        _freeze({"latency_ms": value}),
    )


def _worker(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    peer = snapshot.get("worker_peer") or {}
    if not peer or _has_error(peer):
        return PredicateResult(
            "worker",
            "unknown",
            "worker_peer signal missing",
            _envelope("worker_heartbeat", None, now=now),
            _freeze({"worker_peer": peer}),
        )
    heartbeat = peer.get("heartbeat") if isinstance(peer.get("heartbeat"), dict) else {}
    ts = heartbeat.get("ts")
    if peer.get("expected") is False:
        status, detail = "ok", "worker not required in this process"
    elif peer.get("alive") is True:
        status, detail = "ok", f"peer={peer.get('peer')} source={peer.get('source')}"
    elif peer.get("alive") is False:
        status, detail = "fail", peer.get("note") or "worker peer not alive"
    else:
        status, detail = "unknown", "worker liveness deferred (no HTTP probe)"
    return PredicateResult(
        "worker",
        status,
        detail,
        _envelope(
            "worker_heartbeat",
            ts,
            now=now,
            degraded=peer.get("alive") is False,
        ),
        _freeze({"alive": peer.get("alive"), "expected": peer.get("expected"), "peer": peer.get("peer")}),
    )


def _resolver(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    loop = snapshot.get("loop_health") or {}
    loop_resolver = loop.get("resolver") if isinstance(loop.get("resolver"), dict) else {}
    resolver = snapshot.get("resolver") or {}
    if (_has_error(loop) and _has_error(resolver)) or (not loop_resolver and not resolver):
        return PredicateResult(
            "resolver",
            "unknown",
            "resolver scheduler state missing",
            _envelope("resolver", None, now=now),
            _freeze({}),
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
    failures = int(resolver.get("consecutive_failures") or 0)
    lifecycle = loop_resolver.get("lifecycle") or resolver.get("lifecycle")
    if failures > 0 or last_ok is False:
        status = "fail"
        detail = f"last_ok={last_ok} consecutive_failures={failures}"
    elif loop_resolver.get("warming") or lifecycle in {"starting", "scheduled"}:
        status = "warn"
        detail = f"lifecycle={lifecycle} warming={loop_resolver.get('warming')}"
    elif running is True:
        status = "ok"
        detail = f"running lifecycle={lifecycle}"
    elif running is False:
        status = "fail"
        detail = "resolver not running"
    else:
        status = "unknown"
        detail = "resolver running flag absent"
    return PredicateResult(
        "resolver",
        status,
        detail,
        _envelope("resolver", last_at, now=now, degraded=status == "fail" and last_ok is False),
        _freeze(
            {
                "running": running,
                "last_ok": last_ok,
                "lifecycle": lifecycle,
                "consecutive_failures": failures,
            }
        ),
    )


def _watchdog(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    loop = snapshot.get("loop_health") or {}
    watchdog = snapshot.get("watchdog") or loop.get("watchdog") or {}
    captured = loop.get("checked_at") or loop.get("last_resolver_tick")
    if not watchdog:
        return PredicateResult(
            "watchdog",
            "unknown",
            "resolver watchdog payload missing",
            _envelope("resolver", None, now=now),
            _freeze({}),
        )
    warning = bool(watchdog.get("warning"))
    status = "fail" if warning else "ok"
    detail = watchdog.get("reason") or f"warning={warning} pending={watchdog.get('pending_count')}"
    return PredicateResult(
        "watchdog",
        status,
        str(detail),
        _envelope("resolver", captured, now=now, degraded=warning),
        _freeze(watchdog if isinstance(watchdog, dict) else {}),
    )


def _feed_sync(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    feed = snapshot.get("feed") or {}
    live = snapshot.get("live") or {}
    sync = snapshot.get("sync") or {}
    if _has_error(feed) and _has_error(live):
        return PredicateResult(
            "feed_sync",
            "unknown",
            feed.get("_error") or live.get("_error") or "feed signals missing",
            _envelope("live_feed", None, now=now),
            _freeze({}),
        )
    live_cache = feed.get("live_cache") if isinstance(feed.get("live_cache"), dict) else {}
    captured = (
        live_cache.get("synced_at")
        or live.get("last_sync")
        or sync.get("last_sync_at")
    )
    effective = feed.get("effective_source")
    likely = int(feed.get("likely_total") or 0)
    degraded = effective in (None, "none") or _has_error(feed)
    if degraded:
        status = "fail" if effective == "none" else "unknown"
        detail = f"effective_source={effective} likely_total={likely}"
    elif effective == "registry":
        status = "warn"
        detail = "subnet feed registry-only"
    elif live.get("stale") and int(live.get("subnet_count") or 0) == 0 and likely <= 0:
        status = "fail"
        detail = "live cache empty and stale"
    elif sync.get("last_sync_ok") is False:
        status = "fail"
        detail = "freshness background sync last_sync_ok=false"
    else:
        status = "ok"
        detail = f"effective_source={effective} likely_total={likely}"
    return PredicateResult(
        "feed_sync",
        status,
        detail,
        _envelope("live_feed", captured, now=now, degraded=degraded),
        _freeze(
            {
                "effective_source": effective,
                "likely_total": likely,
                "stale": live.get("stale"),
                "last_sync_ok": sync.get("last_sync_ok"),
            }
        ),
    )


def _cache_age(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    files = snapshot.get("file_freshness") or {}
    live = snapshot.get("live") or {}
    loop = snapshot.get("loop_health") or {}
    if not files and live.get("age_seconds") is None and loop.get("snapshot_age_seconds") is None:
        return PredicateResult(
            "cache_age",
            "unknown",
            "file freshness snapshot missing",
            _envelope("market_data", None, now=now),
            _freeze({}),
        )
    overall = files.get("overall") if isinstance(files.get("overall"), dict) else {}
    price = files.get("price_cache") if isinstance(files.get("price_cache"), dict) else {}
    captured = price.get("last_updated") or live.get("last_sync")
    stale_flags = []
    if overall.get("any_stale"):
        stale_flags.append("file_sources")
    if live.get("stale"):
        stale_flags.append("live_cache")
    snap_age = loop.get("snapshot_age_seconds")
    if isinstance(snap_age, (int, float)) and snap_age > 2700:
        stale_flags.append("score_snapshot")
    if stale_flags:
        status = "fail"
        detail = "stale: " + ",".join(stale_flags)
    else:
        status = "ok"
        detail = f"any_stale={overall.get('any_stale')} live_age={live.get('age_seconds')}"
    return PredicateResult(
        "cache_age",
        status,
        detail,
        _envelope("market_data", captured, now=now, degraded=status == "fail" and not captured),
        _freeze(
            {
                "any_stale": overall.get("any_stale"),
                "live_age_seconds": live.get("age_seconds"),
                "snapshot_age_seconds": snap_age,
            }
        ),
    )


def _scheduler(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    jobs = snapshot.get("job_scheduler") or {}
    pump = snapshot.get("pump_scheduler") or {}
    resolver = snapshot.get("resolver") or {}
    loop = snapshot.get("loop_health") or {}
    pick = loop.get("pick_scheduler") if isinstance(loop.get("pick_scheduler"), dict) else {}
    failures = dict(jobs.get("last_failures") or {})
    failed: list[str] = list(failures.keys())
    if int(resolver.get("consecutive_failures") or 0) > 0:
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
    saw_any = bool(jobs) or bool(pick) or bool(pump) or bool(resolver)
    if failed:
        status = "fail"
        detail = "failures: " + ",".join(failed)
    elif not saw_any:
        status = "unknown"
        detail = "no scheduler state in this process"
    elif jobs.get("running") is False and not captured:
        status = "unknown"
        detail = "background scheduler not running in this process"
    else:
        status = "ok"
        detail = f"apscheduler running={jobs.get('running')} jobs={jobs.get('job_count')}"
    return PredicateResult(
        "scheduler",
        status,
        detail,
        _envelope("resolver", captured, now=now, degraded=status == "fail"),
        _freeze({"last_failures": failures, "failed": failed, "running": jobs.get("running")}),
    )


def _learning(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    loop = snapshot.get("loop_health") or {}
    evidence = snapshot.get("evidence") or {}
    if not loop or _has_error(loop):
        return PredicateResult(
            "learning",
            "unknown",
            loop.get("_error") if isinstance(loop, dict) else "learning health missing",
            _envelope("learning_health", None, now=now),
            _freeze({}),
        )
    status_raw = str(loop.get("status") or "").lower()
    captured = loop.get("checked_at")
    alerts = list(evidence.get("alerts") or [])
    council = ((evidence.get("learning_outcomes") or {}) if isinstance(evidence, dict) else {})
    council_health = (council.get("council_health") or {}) if isinstance(council, dict) else {}
    if status_raw == "stalled" or "council_health ALERT" in alerts:
        status = "fail"
        detail = f"loop_health={status_raw} alerts={alerts[:3]}"
    elif status_raw in {"degraded", "warming"} or str(council_health.get("escalation") or "") == "WATCH":
        status = "warn"
        detail = f"loop_health={status_raw} escalation={council_health.get('escalation')}"
    elif status_raw == "ok":
        status = "ok"
        detail = f"loop_health=ok pending={loop.get('pending')}"
    else:
        status = "unknown"
        detail = f"loop_health status={status_raw or 'missing'}"
    return PredicateResult(
        "learning",
        status,
        detail,
        _envelope(
            "learning_health",
            captured,
            now=now,
            degraded=status_raw in {"degraded", "stalled"} or status == "fail",
        ),
        _freeze(
            {
                "status": loop.get("status"),
                "pending": loop.get("pending"),
                "ledger": loop.get("ledger"),
                "alerts": alerts,
            }
        ),
    )


def _deployment(snapshot: Mapping[str, Any], now: datetime) -> PredicateResult:
    guard = snapshot.get("snapshot_guard") or {}
    loop = snapshot.get("loop_health") or {}
    peer = snapshot.get("worker_peer") or {}
    captured = loop.get("checked_at")
    if guard.get("installed") and guard.get("cold"):
        return PredicateResult(
            "deployment",
            "fail",
            "learning snapshot guard serving cold fallback",
            _envelope("github", captured, now=now, degraded=True),
            _freeze(guard),
        )
    snap_age = loop.get("snapshot_age_seconds")
    worker_alive = peer.get("alive") is True
    if worker_alive and isinstance(snap_age, (int, float)) and snap_age > 2700:
        return PredicateResult(
            "deployment",
            "warn",
            f"score snapshot age {snap_age:.0f}s while worker alive",
            _envelope("github", captured, now=now),
            _freeze({"snapshot_age_seconds": snap_age, "worker_alive": True}),
        )
    if guard.get("installed") and not guard.get("cold"):
        return PredicateResult(
            "deployment",
            "ok",
            "snapshot guard warm",
            _envelope("github", captured, now=now),
            _freeze(guard),
        )
    return PredicateResult(
        "deployment",
        "unknown",
        "no in-process deploy-regression signal (snapshot guard not installed)",
        _envelope("github", None, now=now),
        _freeze({"installed": bool(guard.get("installed"))}),
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
    return tuple(
        PredicateResult(
            name=item.name,
            status=item.status,
            detail=item.detail,
            freshness=_freeze(item.freshness),
            evidence=_freeze(item.evidence),
        )
        for item in (fn(snapshot, reference) for fn in _EVALUATORS)
    )


def _report_status(predicates: Tuple[PredicateResult, ...]) -> str:
    worst = "ok"
    for item in predicates:
        if _STATUS_RANK.get(item.status, 2) > _STATUS_RANK.get(worst, 0):
            worst = item.status
    if worst == "ok":
        return "ok"
    return "degraded"


def observe(*, snapshot: Optional[Mapping[str, Any]] = None) -> HealthReport:
    """Run a read-only health pass and return an immutable report."""
    started = time.perf_counter()
    run_id = uuid.uuid4().hex
    collected = dict(snapshot) if snapshot is not None else collect_snapshot()
    checked_at = str(collected.get("checked_at") or _utcnow_z())
    now = datetime.now(timezone.utc)
    predicates = evaluate_predicates(collected, now=now)
    unknowns = tuple(item.name for item in predicates if item.status == "unknown")
    freshness_sources = [dict(item.freshness) for item in predicates]
    evidence = collected.get("evidence") if isinstance(collected.get("evidence"), dict) else {}
    for extra in evidence.get("evidence_sources") or []:
        if isinstance(extra, Mapping):
            freshness_sources.append(dict(extra))
    freshness = aggregate_freshness(freshness_sources)
    contract = bot_contract(freshness=freshness, state_changing=False)
    ok_n = sum(1 for item in predicates if item.status == "ok")
    confidence = round(ok_n / len(predicates), 3) if predicates else None
    status = _report_status(predicates)
    failed = [item.name for item in predicates if item.status == "fail"]
    warned = [item.name for item in predicates if item.status == "warn"]
    if failed:
        summary = "failing: " + ", ".join(failed)
    elif warned:
        summary = "warnings: " + ", ".join(warned)
    elif unknowns:
        summary = "unknown: " + ", ".join(unknowns)
    else:
        summary = "all ten health predicates ok"
    level = "error" if failed else ("warning" if status == "degraded" else "info")
    log_event(
        "sentinel_health",
        summary=summary,
        level=level,
        run_id=run_id,
        status=status,
        freshness=freshness.get("status"),
    )
    log_event("bot_observe", message=f"sentinel {status}", level="info", run_id=run_id, bot=BOT_NAME)
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
                    "internal.live_subnets.live_data_freshness",
                    "internal.ops.evidence.build_evidence_report",
                    "internal.freshness.get_sync_state",
                ],
                "duration_ms": round((time.perf_counter() - started) * 1000.0, 1),
                "state_changing": False,
            }
        ),
    )
    return report
