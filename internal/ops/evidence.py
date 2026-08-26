"""Read-only ops evidence bundle (pick audit + pump desk + outcomes)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _parse_utc_iso(ts: str) -> Optional[datetime]:
    try:
        raw = str(ts).replace("Z", "+00:00")
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _fresh_enough(ts: Optional[str], max_age_seconds: float = 1200.0) -> bool:
    dt = _parse_utc_iso(ts or "")
    if dt is None:
        return False
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    return age <= max_age_seconds


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def build_evidence_report() -> Dict[str, Any]:
    pick_path = os.path.join("data", "pick_audits", f"{_today()}.json")
    pump_path = os.path.join("data", "pump_desk", "latest.json")
    outcomes_path = os.path.join("data", "learning_outcomes", "latest.json")
    combined_path = os.path.join("data", "learning_outcomes", "combined_angles_effectiveness.json")

    pick = _read_json(pick_path)
    pump = _read_json(pump_path)
    outcomes = _read_json(outcomes_path)
    combined_angles = _read_json(combined_path)
    if combined_angles is None:
        try:
            from internal.pump.combined_ledger import ledger_stats

            combined_angles = {"ledger": ledger_stats(), "artifact_pending": True}
        except Exception:
            combined_angles = None

    alerts: list[str] = []
    if pick and pick.get("verdict") == "MISS":
        alerts.append(f"pick_audit MISS category={pick.get('category')}")
    pump_fresh = pump and _fresh_enough(pump.get("captured_at"))
    if pump_fresh and pump.get("alert_level") == "alert":
        alerts.append("pump_desk alert")
    outcomes_fresh = outcomes and _fresh_enough(outcomes.get("captured_at"))
    if outcomes_fresh and outcomes.get("alert_level") == "alert":
        alerts.append("learning_outcomes alert")

    council = (outcomes or {}).get("council_health") or {}
    escalation = council.get("escalation") or "UNKNOWN"
    if escalation == "ALERT":
        alerts.append("council_health ALERT")
    elif escalation == "WATCH" and not outcomes:
        alerts.append("outcomes artifact missing")

    status = "ok"
    if any("MISS" in a or "alert" in a.lower() or "ALERT" in a for a in alerts):
        status = "alert"
    elif escalation == "WATCH" or (pump_fresh and pump and pump.get("alert_level") == "warn"):
        status = "warn"

    accuracy_lift = _build_accuracy_lift()
    weight_audit = _build_weight_audit()
    capture = _build_capture_evidence()

    return {
        "status": status,
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "alerts": alerts,
        "paths": {
            "pick_audit": pick_path if pick else None,
            "pump_desk": pump_path if pump else None,
            "learning_outcomes": outcomes_path if outcomes else None,
            "combined_angles": combined_path if combined_angles else None,
        },
        "combined_angles": combined_angles,
        "pick_audit": {
            "verdict": pick.get("verdict") if pick else None,
            "category": pick.get("category") if pick else None,
            "published_netuid": pick.get("published_netuid") if pick else None,
        },
        "pump_desk": {
            "alert_level": pump.get("alert_level") if pump else None,
            "captured_at": pump.get("captured_at") if pump else None,
        },
        "learning_outcomes": {
            "alert_level": outcomes.get("alert_level") if outcomes else None,
            "captured_at": outcomes.get("captured_at") if outcomes else None,
            "council_health": council if outcomes else None,
        },
        "accuracy_lift": accuracy_lift,
        "attribution_quality": accuracy_lift.get("attribution_quality") or {},
        "weight_audit": weight_audit,
        "capture": capture,
    }


def _build_accuracy_lift() -> Dict[str, Any]:
    try:
        from internal.accuracy_lift.measure import build_accuracy_lift_snapshot

        return build_accuracy_lift_snapshot()
    except Exception:
        return {
            "data_available": False,
            "graded_7d": 0,
            "graded_30d": 0,
            "hit_rate_7d": None,
            "hit_rate_30d": None,
            "by_expert": {},
            "attribution_quality": {"total": 0, "unknown": 0, "unknown_pct": None, "attributed": 0},
            "published_only": {
                "graded_7d": 0,
                "hit_rate_7d": None,
                "graded_30d": 0,
                "hit_rate_30d": None,
            },
            "council_trust": {
                "graded_7d": 0,
                "hit_rate_7d": None,
                "graded_30d": 0,
                "hit_rate_30d": None,
            },
            "full_ledger": {
                "graded_7d": 0,
                "hit_rate_7d": None,
                "graded_30d": 0,
                "hit_rate_30d": None,
            },
            "by_pick_source": {},
            "by_pick_source_30d": [],
            "by_horizon_30d": [],
            "window_actual_days": {"w7": None, "w30": None},
            "small_move_miss_share": {"misses": 0, "small_move_misses": 0, "share": None},
            "note": "honest empty until graded>0",
        }


def _build_capture_evidence() -> Dict[str, Any]:
    try:
        from internal.council.capture import build_capture_telemetry
        from internal.learning.predictions_store import load_predictions

        rows = load_predictions().get("resolved") or []
        return build_capture_telemetry(rows)
    except Exception:
        return {
            "outcomes": {
                "hit": 0,
                "near_hit": 0,
                "noise": 0,
                "ungradeable": 0,
                "miss": 0,
            },
            "epsilon_hit_share": None,
            "near_hit_rate": None,
            "capture_histogram": {"0-25": 0, "25-50": 0, "50-100": 0, ">100": 0},
            "avg_capture_by_expert": {},
            "hit_rate_strict": None,
            "hit_rate_sign_only_legacy": None,
            "volatility_deadband": {},
            "rows": [],
            "headline_mode": "legacy",
            "note": "capture window capped at last 500 resolved",
        }


def _build_weight_audit() -> Dict[str, Any]:
    try:
        from internal.learning.weight_audit import build_weight_audit_report

        return build_weight_audit_report()
    except Exception:
        return {
            "read_only": True,
            "online_path": {},
            "expert_weights": {},
            "judge_weights": {},
            "known_gaps": [],
            "tune_gate": {"recommendation": "audit unavailable"},
        }
