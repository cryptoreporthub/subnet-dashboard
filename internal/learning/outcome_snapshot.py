"""Learning outcome snapshot — evidence loop for resolver accuracy (not selection).

Writes ``data/learning_outcomes/`` for Ditto Council Health Monitor + GHA probes.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

OUTCOMES_DIR = os.environ.get("LEARNING_OUTCOMES_DIR", os.path.join("data", "learning_outcomes"))


def _outcomes_dir() -> str:
    return os.environ.get("LEARNING_OUTCOMES_DIR", OUTCOMES_DIR)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _snapshot_path(ts: Optional[str] = None) -> str:
    name = ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    return os.path.join(_outcomes_dir(), "snapshots", f"{name}.json")


def _latest_path() -> str:
    return os.path.join(_outcomes_dir(), "latest.json")


def _read_json_if_exists(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("outcome snapshot: could not read %s: %s", path, exc)
        return None


def _artifact_refs() -> Dict[str, Any]:
    pick_audit = _read_json_if_exists(os.path.join("data", "pick_audits", _today_str() + ".json"))
    pump = _read_json_if_exists(os.path.join("data", "pump_desk", "latest.json"))
    refs: Dict[str, Any] = {}
    if pick_audit:
        refs["pick_audit"] = {
            "pick_date": pick_audit.get("pick_date"),
            "verdict": pick_audit.get("verdict"),
            "category": pick_audit.get("category"),
            "published_netuid": pick_audit.get("published_netuid"),
        }
    if pump:
        refs["pump_desk"] = {
            "captured_at": pump.get("captured_at"),
            "alert_level": pump.get("alert_level"),
        }
    return refs


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _collect_learning_snapshot() -> Dict[str, Any]:
    from internal.council.resolver import get_resolved_predictions
    from internal.council.watchdog import check_resolver_watchdog
    from internal.learning.predictions_store import load_predictions
    from internal.learning.trust_stats import build_trust_banner

    resolved_payload = get_resolved_predictions()
    resolver_stats = resolved_payload.get("stats", {}) or {}
    pending_rows = load_predictions().get("predictions", []) or []
    watchdog = check_resolver_watchdog(pending_rows)
    trust_banner = build_trust_banner(resolver_stats, watchdog=watchdog)

    try:
        from internal.learning.loop_health import build_learning_loop_health

        loop_health = build_learning_loop_health()
    except Exception as exc:
        logger.warning("outcome snapshot: loop health failed: %s", exc)
        loop_health = {"status": "error", "error": str(exc)}

    try:
        from internal.learning.routes import _learning_snapshot

        snap = _learning_snapshot()
        expert_weights = snap.get("expert_weights") or {}
    except Exception as exc:
        logger.warning("outcome snapshot: expert weights failed: %s", exc)
        expert_weights = {}

    from internal.learning.council_health_score import compute_council_health

    council = compute_council_health(resolver_stats, trust_banner, loop_health)

    streak = trust_banner.get("streak") or {}
    return {
        "resolver_stats": {
            "total": resolver_stats.get("total"),
            "correct": resolver_stats.get("correct"),
            "wrong": resolver_stats.get("wrong"),
            "pending": resolver_stats.get("pending"),
            "expired": resolver_stats.get("expired"),
            "accuracy": resolver_stats.get("accuracy"),
        },
        "trust_banner": {
            "ready": trust_banner.get("ready"),
            "integrity_gate": trust_banner.get("integrity_gate"),
            "expired_rate": trust_banner.get("expired_rate"),
        },
        "watchdog": watchdog,
        "loop_health": {
            "status": loop_health.get("status"),
            "pending": loop_health.get("pending"),
            "worker_peer_alive": (loop_health.get("worker_peer") or {}).get("alive"),
        },
        "expert_weights": expert_weights,
        "streak": streak,
        "council_health": council,
    }


def _evaluate_alerts(payload: Dict[str, Any]) -> Tuple[str, List[str]]:
    reasons: List[str] = []
    council = payload.get("council_health") or {}
    escalation = str(council.get("escalation") or "OK").upper()
    reasons.extend(council.get("escalation_reasons") or [])

    loop_status = str((payload.get("loop_health") or {}).get("status") or "").lower()
    if loop_status in ("stalled", "error"):
        reasons.append(f"learning_loop status={loop_status}")

    if escalation == "ALERT" or loop_status in ("stalled", "error"):
        return "alert", reasons
    if escalation == "WATCH":
        return "warn", reasons
    return "ok", reasons


def build_outcome_snapshot() -> Dict[str, Any]:
    core = _collect_learning_snapshot()
    level, reasons = _evaluate_alerts(core)
    return {
        "status": "ok",
        "captured_at": _utcnow_iso(),
        "alert_level": level,
        "alert_reasons": reasons,
        **core,
        "artifact_refs": _artifact_refs(),
    }


def save_snapshot(payload: Dict[str, Any]) -> str:
    desk = _outcomes_dir()
    os.makedirs(os.path.join(desk, "snapshots"), exist_ok=True)
    path = _snapshot_path()
    latest = _latest_path()
    for target in (path, latest):
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, target)
    return path


def run_snapshot(*, save: bool = True) -> Dict[str, Any]:
    payload = build_outcome_snapshot()
    if save:
        payload["path"] = save_snapshot(payload)
    return payload


def exit_code_for_level(level: str) -> int:
    if level == "alert":
        return 2
    return 0
