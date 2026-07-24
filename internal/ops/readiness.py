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


def build_readiness_report() -> Dict[str, Any]:
    """Aggregate scheduler, volume, feed, and cred signals for operators."""
    issues: List[str] = []

    from internal.live_subnets import live_data_freshness
    from internal.freshness import get_sync_state
    from internal.council.resolver_scheduler import get_prediction_resolver_scheduler_state

    live = live_data_freshness()
    feed = probe_feed_layers()
    sync = get_sync_state()
    resolver = get_prediction_resolver_scheduler_state()
    learning = _learning_summary()
    daily = _daily_pick_summary()

    from internal.run_mode import inline_worker_expected, worker_mode_label

    inline_worker = inline_worker_expected()
    worker_peer_alive = False
    worker_peer: Dict[str, Any] = {"expected": inline_worker, "alive": False}
    if inline_worker:
        from internal.worker_heartbeat import is_alive, read_heartbeat

        worker_peer_alive = is_alive()
        worker_peer = {
            "expected": True,
            "alive": worker_peer_alive,
            "heartbeat": read_heartbeat(),
        }
        if worker_peer_alive:
            resolver = {**resolver, "running": True, "peer": "inline_worker"}

    try:
        from fetchers.taostats_client import is_available as taostats_available
    except Exception:
        taostats_available = lambda: False  # noqa: E731

    taostats = bool(taostats_available())

    if learning.get("graded", 0) <= 0:
        issues.append("learning_loop_has_no_graded_picks")
    if inline_worker and not worker_peer_alive:
        issues.append("inline_worker_not_running")
    if not resolver.get("running"):
        issues.append("prediction_resolver_not_running")
    if feed.get("likely_total", 0) <= 0:
        issues.append("subnet_feed_empty")
    elif feed.get("effective_source") == "registry":
        issues.append("subnet_feed_registry_only")
    if live.get("stale") and live.get("subnet_count", 0) == 0:
        issues.append("live_subnets_cache_empty")
    if not taostats:
        issues.append("taostats_api_key_missing")
    if daily.get("action") == "HOLD" and not daily.get("published"):
        issues.append("daily_pick_hold_no_published_long")

    thin_ui = feed.get("likely_total", 0) <= 0 or feed.get("effective_source") == "none"

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
        "resolver": resolver,
        "registry_sync": {
            "background_running": sync.get("background_running"),
            "last_sync_at": sync.get("last_sync_at"),
            "last_sync_ok": sync.get("last_sync_ok"),
        },
        "live_cache": live,
        "subnet_feed": feed,
        "subnet_feed_meta": subnet_feed_meta(
            [{"source": feed.get("effective_source")}] if feed.get("effective_source") else []
        ),
        "taostats": {"configured": taostats},
        "daily_pick": daily,
        "next_levers": _next_levers(issues, taostats),
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
    if "daily_pick_hold_no_published_long" in issues:
        levers.append("hold_is_honest_when_below_audit_gate_not_a_feed_outage")
    if not levers:
        levers.append("volume_and_scheduler_healthy")
    return levers
