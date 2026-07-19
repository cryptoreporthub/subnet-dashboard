"""K3-8 Pump Alert lane — PUMPING / COOLING rows separate from dossier."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from internal.learning.dpick_copy import hero_copy_is_clean

_EMPTY_MESSAGE = (
    "No names in PUMPING right now. Early heat stays on the dossier chip when the lead is warming."
)
_MAX_PUMPING = 5
_MAX_COOLING = 2


def _subnet_row(netuid: int, subnets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for row in subnets:
        if row.get("netuid") == netuid:
            return row
    return None


def _lead_signals(
    subnet_row: Optional[Dict[str, Any]],
    ladder_entry: Dict[str, Any],
) -> Dict[str, Optional[float]]:
    snapshot: Dict[str, Any] = {}
    raw = ladder_entry.get("signal_snapshot")
    if isinstance(raw, dict):
        snapshot = raw
    if not snapshot and isinstance(subnet_row, dict):
        from internal.pump.signals import build_subnet_signals

        snapshot = build_subnet_signals(subnet_row)
    try:
        buy_ratio = float(snapshot.get("buy_ratio", 0.5))
    except (TypeError, ValueError):
        buy_ratio = None
    try:
        volume_intensity = float(snapshot.get("volume_intensity", 0.0))
    except (TypeError, ValueError):
        volume_intensity = None
    return {"buy_ratio": buy_ratio, "volume_intensity": volume_intensity}


def _move_line(name: str, netuid: Any, phase: str) -> str:
    label = str(name or f"SN{netuid}").strip()
    prefix = "IN PLAY" if phase == "PUMPING" else "FADING"
    if re.match(r"^SN\d+$", label, re.I):
        return f"{prefix} · {label}"
    if netuid is not None:
        return f"{prefix} · {label} (SN{netuid})"
    return f"{prefix} · {label}"


def _row_copy(
    phase: str,
    buy_ratio: Optional[float],
    volume_intensity: Optional[float],
) -> Dict[str, str]:
    lead = ""
    if buy_ratio is not None and volume_intensity is not None:
        lead = f" Flow {buy_ratio:.0%} buy · vol {volume_intensity:.0%}."
    if phase == "PUMPING":
        return {
            "thesis": (
                "Ladder says PUMPING — buy flow and volume already aligned. "
                "This is motion, not the early heat chip." + lead
            ),
            "trigger": "Late if you chase; watch for COOLING before adding.",
            "badge": "PUMPING",
        }
    return {
        "thesis": "Heat rolling off — ladder in COOLING." + lead,
        "trigger": "Don't treat as a fresh pump entry.",
        "badge": "FADING",
    }


def build_alert_row(
    ladder_entry: Dict[str, Any],
    subnet_row: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    phase = str(ladder_entry.get("phase") or "DORMANT").upper()
    netuid = ladder_entry.get("netuid")
    try:
        netuid_int = int(netuid) if netuid is not None else None
    except (TypeError, ValueError):
        netuid_int = None
    name = str(ladder_entry.get("name") or (f"SN{netuid_int}" if netuid_int is not None else "subnet"))
    leads = _lead_signals(subnet_row, ladder_entry)
    copy = _row_copy(phase, leads["buy_ratio"], leads["volume_intensity"])
    try:
        score = float(ladder_entry.get("composite_score") or 0.0)
    except (TypeError, ValueError):
        score = None
    row = {
        "netuid": netuid_int,
        "name": name,
        "phase": phase,
        "score": round(score, 2) if score is not None else None,
        "move": _move_line(name, netuid_int, phase),
        "thesis": copy["thesis"],
        "trigger": copy["trigger"],
        "badge": copy["badge"],
        "buy_ratio": leads["buy_ratio"],
        "volume_intensity": leads["volume_intensity"],
        "updated_at": ladder_entry.get("updated_at"),
    }
    return row


def build_pump_alerts(subnets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Return Pump Alert lane payload for SSR + GET /api/pump-alerts."""
    rows = subnets if isinstance(subnets, list) else []
    try:
        from internal.pump.state import load_state

        state = load_state()
    except Exception as exc:
        return {
            "status": "unavailable",
            "count": 0,
            "alerts": [],
            "empty_message": _EMPTY_MESSAGE,
            "error": str(exc),
        }

    pumping: List[Dict[str, Any]] = []
    cooling: List[Dict[str, Any]] = []
    for entry in (state.get("subnets") or {}).values():
        if not isinstance(entry, dict):
            continue
        phase = str(entry.get("phase") or "").upper()
        netuid = entry.get("netuid")
        row = _subnet_row(int(netuid), rows) if netuid is not None else None
        if phase == "PUMPING":
            pumping.append((float(entry.get("composite_score") or 0.0), entry, row))
        elif phase == "COOLING":
            cooling.append((float(entry.get("composite_score") or 0.0), entry, row))

    pumping.sort(key=lambda t: t[0], reverse=True)
    cooling.sort(key=lambda t: t[0], reverse=True)
    alerts = [
        build_alert_row(entry, row)
        for _, entry, row in pumping[:_MAX_PUMPING]
    ] + [
        build_alert_row(entry, row)
        for _, entry, row in cooling[:_MAX_COOLING]
    ]

    for alert in alerts:
        brief = {"move": alert["move"], "thesis": alert["thesis"]}
        if not hero_copy_is_clean(brief):
            alert["thesis"] = alert["thesis"].replace("audit gate", "bar")

    count = len([a for a in alerts if a.get("phase") == "PUMPING"])
    status = "success" if count else "empty"
    return {
        "status": status,
        "count": count,
        "alerts": alerts,
        "empty_message": _EMPTY_MESSAGE,
        "error": None,
    }
