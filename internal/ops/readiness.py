"""Production readiness probe — one JSON surface for ops (§33)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from internal.subnets.feed import probe_feed_layers, subnet_feed_meta


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _daily_pick_summary() -> Dict[str, Any]:
    path = os.environ.get("DAILY_PICKS_PATH", "data/daily_picks.json")
    today = datetime.now(timezone.utc).date().isoformat()
    out: Dict[str, Any] = {
        "date": today,
        "action": None,
        "published": False,
        "candidate": False,
        "reason": None,
    }
    try:
        with open(path, "r") as f:
            records = json.load(f)
        if not isinstance(records, list):
            return out
        for rec in reversed(records):
            if rec.get("date") != today:
                continue
            out["action"] = rec.get("action")
            out["published"] = bool(rec.get("published"))
            out["candidate"] = bool(rec.get("candidate"))
            out["reason"] = rec.get("reason") or rec.get("hold_reason")
            pick = rec.get("pick") or {}
            if isinstance(pick, dict):
                out["pick_netuid"] = pick.get("netuid") or (pick.get("subnet") or {}).get("netuid")
                out["pick_confidence"] = pick.get("confidence")
            break
    except Exception:
        pass
    return out


def _learning_loop_health() -> Dict[str, Any]:
    """Volume truth on split_v2 web — proxy worker /api/learning/health when local data is orphan."""
    try:
        from internal.data_volume import needs_worker_volume_proxy

        if needs_worker_volume_proxy():
            from internal.worker_proxy import fetch_worker_json_sync

            remote = fetch_worker_json_sync("/api/learning/health")
            if isinstance(remote, dict) and remote.get("status"):
                return remote
    except Exception:
        pass
    try:
        from internal.learning.loop_health import build_learning_loop_health

        return build_learning_loop_health()
    except Exception:
        return {}


def _learning_summary() -> Dict[str, Any]:
    try:
        from internal.learning.routes import _learning_snapshot

        snap = _learning_snapshot()
        stats = snap.get("engine_stats") or {}
        resolver_stats = snap.get("resolver_stats") or {}
        trust = snap.get("trust_banner") or {}
        graded = int(
            trust.get("graded")
            or resolver_stats.get("graded")
            or stats.get("graded")
            or stats.get("resolved")
            or 0
        )
        return {
            "graded": graded,
            "pending": int(
                trust.get("pending")
                or stats.get("pending")
                or resolver_stats.get("pending")
                or 0
            ),
            "accuracy": trust.get("accuracy") or stats.get("accuracy"),
            "trust_ready": trust.get("ready"),
            "trust_label": trust.get("label") or trust.get("headline"),
        }
    except Exception:
        return {"graded": 0, "pending": 0, "accuracy": None, "trust_ready": None}


def _scheduler_view_from_tracker(
    snap: Dict[str, Any],
    *,
    peer: str | None = None,
    force_running: bool = False,
) -> Dict[str, Any]:
    """Map a liveness registry snapshot to the legacy resolver scheduler shape."""
    if not snap:
        return {
            "running": bool(force_running),
            "lifecycle": "stopped",
            "status": None,
            "peer": peer,
        }
    lifecycle = snap.get("lifecycle")
    status = snap.get("status")
    running = bool(force_running) or lifecycle == "started"
    return {
        "running": running,
        "lifecycle": lifecycle,
        "status": status,
        "status_reason": snap.get("status_reason"),
        "last_run_at": snap.get("last_event_at"),
        "last_run_ok": status == "ok",
        "last_success_at": snap.get("last_success_at"),
        "success_age_seconds": snap.get("success_age_seconds"),
        "consecutive_failures": snap.get("consecutive_failures"),
        "consecutive_skips": snap.get("consecutive_skips"),
        "source": snap.get("source"),
        "peer": peer,
    }


def _pump_desk_trust_from_liveness(registry: Dict[str, Any]) -> Dict[str, Any]:
    """Age-derived pump desk trust gate (spec §1 — status ok is never stored)."""
    snap = (registry.get("trackers") or {}).get("pump_ladder") or {}
    status = snap.get("status")
    ready = status == "ok"
    return {
        "ready": ready,
        "liveness_status": status,
        "success_age_seconds": snap.get("success_age_seconds"),
        "last_success_at": snap.get("last_success_at"),
        "source": "liveness_registry",
    }


def build_liveness_report(*, probe_worker: bool = True) -> Dict[str, Any]:
    """Fast liveness probe — file/heartbeat only by default on hot paths.

    ``probe_worker=False`` skips the split_v2 HTTP peer round-trip so
    ``/api/ops/live`` (InstantBailoutASGI) never blocks the event loop ~36s.
    """
    from internal.run_mode import worker_mode_label
    from internal.worker_peer import get_worker_peer

    if probe_worker:
        worker_peer = get_worker_peer()
    else:
        from internal.run_mode import split_worker_v2_enabled

        worker_peer = (
            {"expected": True, "alive": None, "peer": "dedicated_worker", "source": "deferred"}
            if split_worker_v2_enabled()
            else get_worker_peer(max_age_seconds=180)
        )

    data_dir = os.environ.get("DATA_DIR", "data")
    volume_ok = os.path.isdir(data_dir) and os.access(data_dir, os.W_OK)

    return {
        "status": "ok" if volume_ok else "degraded",
        "checked_at": _utcnow_z(),
        "live": True,
        "volume": {"path": data_dir, "writable": volume_ok},
        "worker_mode": worker_mode_label(),
        "worker_peer": worker_peer,
    }


def build_readiness_report() -> Dict[str, Any]:
    """Aggregate scheduler, volume, feed, and cred signals for operators."""
    issues: List[str] = []

    from internal.live_subnets import live_data_freshness
    from internal.freshness import get_sync_state
    from internal.liveness import build_liveness_registry

    live = live_data_freshness()
    feed = probe_feed_layers()
    sync = get_sync_state()
    liveness = build_liveness_registry()
    trackers = liveness.get("trackers") or {}
    resolver_snap = trackers.get("prediction_resolver") or {}
    learning = _learning_summary()
    daily = _daily_pick_summary()
    pump_desk_trust = _pump_desk_trust_from_liveness(liveness)

    loop_health = _learning_loop_health()
    if loop_health.get("status") == "stalled":
        issues.append("learning_loop_stalled")
    elif loop_health.get("ledger", {}).get("gap"):
        issues.append("daily_pick_ledger_gap")

    from internal.run_mode import inline_worker_expected, is_worker_mode, split_worker_v2_enabled, worker_mode_label
    from internal.worker_peer import get_worker_peer

    inline_worker = inline_worker_expected()
    split_v2 = split_worker_v2_enabled()
    worker_peer = get_worker_peer()
    worker_peer_alive = bool(worker_peer.get("alive"))
    if is_worker_mode() and worker_peer_alive:
        resolver = _scheduler_view_from_tracker(
            resolver_snap, peer="dedicated_worker", force_running=True
        )
    elif inline_worker and worker_peer_alive:
        resolver = _scheduler_view_from_tracker(
            resolver_snap, peer="inline_worker", force_running=True
        )
    elif split_v2 and not is_worker_mode() and worker_peer_alive:
        resolver = _scheduler_view_from_tracker(
            resolver_snap, peer="dedicated_worker", force_running=True
        )
    else:
        resolver = _scheduler_view_from_tracker(resolver_snap)

    try:
        from fetchers.taostats_client import is_available as taostats_available
    except Exception:
        taostats_available = lambda: False  # noqa: E731

    taostats = bool(taostats_available())

    if learning.get("graded", 0) <= 0:
        issues.append("learning_loop_has_no_graded_picks")
    if inline_worker and not worker_peer_alive:
        issues.append("inline_worker_not_running")
    if split_v2 and not is_worker_mode() and worker_peer.get("alive") is False:
        issues.append("dedicated_worker_not_running")
    if not resolver.get("running") and not (split_v2 and not is_worker_mode()):
        issues.append("prediction_resolver_not_running")
    registry_warming = bool(
        sync.get("background_running")
        and sync.get("last_sync_at") is None
        and feed.get("likely_total", 0) <= 0
    )
    if registry_warming:
        issues.append("subnet_feed_warming")
    elif feed.get("likely_total", 0) <= 0:
        issues.append("subnet_feed_empty")
    elif feed.get("effective_source") == "registry":
        issues.append("subnet_feed_registry_only")
    feed_ok = feed.get("likely_total", 0) > 0 and feed.get("effective_source") not in (
        "none",
        "registry",
    )
    if live.get("stale") and live.get("subnet_count", 0) == 0 and not feed_ok:
        issues.append("live_subnets_cache_empty")
    if not taostats:
        issues.append("taostats_api_key_missing")
    if daily.get("action") == "HOLD" and not daily.get("published"):
        issues.append("daily_pick_hold_no_published_long")

    thin_ui = feed.get("likely_total", 0) <= 0 or feed.get("effective_source") == "none"

    from internal.ops.bot_policy import bot_contract, classify_freshness

    heartbeat = worker_peer.get("heartbeat")
    heartbeat_ts = heartbeat.get("ts") if isinstance(heartbeat, dict) else None
    freshness_sources = [
        classify_freshness(
            "live_feed",
            (feed.get("live_cache") or {}).get("synced_at")
            or live.get("last_sync")
            or sync.get("last_sync_at"),
            degraded=feed.get("effective_source") in (None, "none"),
        ),
        classify_freshness(
            "resolver",
            resolver.get("last_success_at")
            or resolver.get("last_run_at"),
            degraded=bool(resolver.get("running") is False and (inline_worker or split_v2)),
        ),
        classify_freshness(
            "learning_health",
            loop_health.get("checked_at") if isinstance(loop_health, dict) else None,
            degraded=loop_health.get("status") == "degraded",
        ),
    ]
    if worker_peer.get("expected"):
        freshness_sources.append(
            classify_freshness(
                "worker_heartbeat",
                heartbeat_ts,
                degraded=worker_peer.get("alive") is False,
            )
        )
    readiness_contract = bot_contract(sources=freshness_sources)

    ready = not any(
        i in issues
        for i in (
            "learning_loop_has_no_graded_picks",
            "prediction_resolver_not_running",
            "subnet_feed_empty",
        )
    )

    return {
        "status": "ready" if ready else "degraded",
        "checked_at": _utcnow_z(),
        "ready": ready,
        "worker_mode": worker_mode_label(),
        "worker_peer": worker_peer,
        "thin_ui_likely": thin_ui,
        "issues": issues,
        "learning": learning,
        "learning_loop_health": loop_health,
        "liveness": liveness,
        "resolver": resolver,
        "pump_desk_trust": pump_desk_trust,
        "registry_sync": {
            "background_running": sync.get("background_running"),
            "last_sync_at": sync.get("last_sync_at"),
            "last_sync_ok": sync.get("last_sync_ok"),
            "warming": registry_warming,
        },
        "live_cache": live,
        "subnet_feed": feed,
        "subnet_feed_meta": subnet_feed_meta(
            [{"source": feed.get("effective_source")}] if feed.get("effective_source") else []
        ),
        "taostats": {"configured": taostats},
        "daily_pick": daily,
        "next_levers": _next_levers(issues, taostats),
        "evidence_sources": freshness_sources,
        **readiness_contract,
    }


def _next_levers(issues: List[str], taostats: bool) -> List[str]:
    levers: List[str] = []
    if "live_subnets_cache_empty" in issues or "subnet_feed_registry_only" in issues:
        levers.append("wait_for_blockmachine_sync_or_check_volume_mount")
        levers.append("confirm_machine_has_1gb_and_auto_stop_off")
    if not taostats:
        levers.append("set_TAOSTATS_API_KEY_via_flyctl_secrets")
    if "prediction_resolver_not_running" in issues:
        levers.append("check_resolver_at_GET_/api/predictions/resolver")
    if "inline_worker_not_running" in issues:
        levers.append("check_inline_worker_heartbeat_data/.worker_heartbeat")
    if "dedicated_worker_not_running" in issues:
        levers.append("check_worker_machine_fly_scale_count_worker_1")
        levers.append("check_worker_logs_fly_logs_p_worker")
    if "daily_pick_hold_no_published_long" in issues:
        levers.append("hold_is_honest_when_below_audit_gate_not_a_feed_outage")
    if "learning_loop_stalled" in issues or "daily_pick_ledger_gap" in issues:
        levers.append("check_GET_/api/learning/health_ledger_gap_phase1_schedulers")
    if not levers:
        levers.append("volume_and_scheduler_healthy")
    return levers
