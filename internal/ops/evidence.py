"""Read-only ops evidence bundle (pick audit + pump desk + outcomes)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional


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

    pick = _read_json(pick_path)
    pump = _read_json(pump_path)
    outcomes = _read_json(outcomes_path)

    alerts: list[str] = []
    if pick and pick.get("verdict") == "MISS":
        alerts.append(f"pick_audit MISS category={pick.get('category')}")
    if pump and pump.get("alert_level") == "alert":
        alerts.append("pump_desk alert")
    if outcomes and outcomes.get("alert_level") == "alert":
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
    elif escalation == "WATCH" or (pump and pump.get("alert_level") == "warn"):
        status = "warn"

    return {
        "status": status,
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "alerts": alerts,
        "paths": {
            "pick_audit": pick_path if pick else None,
            "pump_desk": pump_path if pump else None,
            "learning_outcomes": outcomes_path if outcomes else None,
        },
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
    }
