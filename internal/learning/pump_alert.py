"""K3-8b Pump lane — predictive lead scanner (flow before price)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from internal.learning.dpick_copy import hero_copy_is_clean

_EMPTY_MESSAGE = (
    "No lead or confirmed motion right now. Early heat on today's pick stays on the "
    "dossier chip when flow warms."
)
_MAX_EARLY = 5
_MAX_PUMPING = 3
_MAX_COOLING = 2
_LEAD_BUY_RATIO_MIN = 0.55
_LEAD_VOLUME_INTENSITY_MIN = 0.22
_EARLY_PHASES = frozenset({"STIRRING", "ACCUMULATING"})
_BAD_NAME = re.compile(r"^(unknown|deprecated|none|snnone|unnamed)$", re.I)


def _resolve_name(
    ladder_entry: Dict[str, Any],
    subnet_row: Optional[Dict[str, Any]],
) -> str:
    netuid = ladder_entry.get("netuid")
    try:
        netuid_int = int(netuid) if netuid is not None else None
    except (TypeError, ValueError):
        netuid_int = None

    candidates: List[str] = []
    for src in (subnet_row, ladder_entry):
        if not isinstance(src, dict):
            continue
        raw = src.get("name") or src.get("subnet_name")
        if raw and not _BAD_NAME.match(str(raw).strip()):
            candidates.append(str(raw).strip())

    if candidates:
        return candidates[0]

    if netuid_int is not None:
        try:
            from internal.subnet_names import resolve_subnet_name

            resolved = resolve_subnet_name(netuid_int, tmc_name=ladder_entry.get("name"))
            if resolved and not _BAD_NAME.match(resolved):
                return resolved
        except Exception:
            pass
        return f"SN{netuid_int}"
    return "subnet"


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


def _lead_qualifies(buy_ratio: Optional[float], volume_intensity: Optional[float]) -> bool:
    if buy_ratio is None or volume_intensity is None:
        return False
    return buy_ratio >= _LEAD_BUY_RATIO_MIN and volume_intensity >= _LEAD_VOLUME_INTENSITY_MIN


def _display_label(name: str, netuid: Optional[int]) -> str:
    label = str(name or "").strip()
    if netuid is not None and not re.search(rf"\(SN{netuid}\)", label, re.I):
        if re.match(r"^SN\d+$", label, re.I):
            return label
        return f"{label} (SN{netuid})"
    return label or (f"SN{netuid}" if netuid is not None else "subnet")


def _move_line(prefix: str, name: str, netuid: Optional[int]) -> str:
    return f"{prefix} · {_display_label(name, netuid)}"


def _row_copy(
    phase: str,
    name: str,
    buy_ratio: Optional[float],
    volume_intensity: Optional[float],
    netuid_int: Optional[int],
) -> Dict[str, str]:
    if phase == "STIRRING":
        br = buy_ratio if buy_ratio is not None else 0.5
        vi = volume_intensity if volume_intensity is not None else 0.0
        return {
            "move": _move_line("WATCH", name, netuid_int),
            "badge": "EARLY",
            "timing": "lead",
            "thesis": (
                f"Buy pressure building before price runs — {br:.0%} buy flow, "
                f"volume still warming ({vi:.0%})."
            ),
            "trigger": "Entry window open — small size now or wait for BUILDING confirmation.",
        }
    if phase == "ACCUMULATING":
        br = buy_ratio if buy_ratio is not None else 0.5
        vi = volume_intensity if volume_intensity is not None else 0.0
        return {
            "move": _move_line("BUILDING", name, netuid_int),
            "badge": "BUILDING",
            "timing": "lead",
            "thesis": (
                f"Flow and volume aligning ahead of price — {br:.0%} buys, vol {vi:.0%}."
            ),
            "trigger": "Best risk/reward band — chase only if you miss this window.",
        }
    if phase == "PUMPING":
        return {
            "move": _move_line("CONFIRMED", name, netuid_int),
            "badge": "CHASE RISK",
            "timing": "confirmed",
            "thesis": (
                "Move is live — you are not early. Use for exit sizing and rotation, "
                "not fresh entry."
            ),
            "trigger": "Do not chase; trim on EXIT WATCH or rotate to BUILDING names.",
        }
    br = buy_ratio if buy_ratio is not None else 0.5
    return {
        "move": _move_line("EXIT WATCH", name, netuid_int),
        "badge": "FADING",
        "timing": "exit",
        "thesis": (
            f"Buyers stepping away while price may still look hot — {br:.0%} buy flow left."
        ),
        "trigger": "Reduce exposure; lead is shifting to names still BUILDING.",
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
    name = _resolve_name(ladder_entry, subnet_row)
    leads = _lead_signals(subnet_row, ladder_entry)
    try:
        score = float(ladder_entry.get("composite_score") or 0.0)
    except (TypeError, ValueError):
        score = None
    copy = _row_copy(phase, name, leads["buy_ratio"], leads["volume_intensity"], netuid_int)
    row = {
        "netuid": netuid_int,
        "name": name,
        "phase": phase,
        "timing": copy["timing"],
        "score": round(score, 2) if score is not None else None,
        "move": copy["move"],
        "thesis": copy["thesis"],
        "trigger": copy["trigger"],
        "badge": copy["badge"],
        "buy_ratio": leads["buy_ratio"],
        "volume_intensity": leads["volume_intensity"],
        "updated_at": ladder_entry.get("updated_at"),
    }
    return row


def _sort_bucket(
    entries: List[Tuple[float, Dict[str, Any], Optional[Dict[str, Any]]]],
    limit: int,
) -> List[Dict[str, Any]]:
    entries.sort(key=lambda t: t[0], reverse=True)
    return [build_alert_row(entry, row) for _, entry, row in entries[:limit]]


def build_pump_alerts(subnets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Return predictive pump lane payload for SSR + GET /api/pump-alerts."""
    rows = subnets if isinstance(subnets, list) else []
    try:
        from internal.pump.state import load_state

        state = load_state()
    except Exception as exc:
        return {
            "status": "unavailable",
            "count": 0,
            "early_count": 0,
            "confirmed_count": 0,
            "alerts": [],
            "empty_message": _EMPTY_MESSAGE,
            "error": str(exc),
        }

    early: List[Tuple[float, Dict[str, Any], Optional[Dict[str, Any]]]] = []
    pumping: List[Tuple[float, Dict[str, Any], Optional[Dict[str, Any]]]] = []
    cooling: List[Tuple[float, Dict[str, Any], Optional[Dict[str, Any]]]] = []

    for entry in (state.get("subnets") or {}).values():
        if not isinstance(entry, dict):
            continue
        phase = str(entry.get("phase") or "").upper()
        netuid = entry.get("netuid")
        subnet = _subnet_row(int(netuid), rows) if netuid is not None else None
        score = float(entry.get("composite_score") or 0.0)
        if phase in _EARLY_PHASES:
            leads = _lead_signals(subnet, entry)
            if _lead_qualifies(leads["buy_ratio"], leads["volume_intensity"]):
                early.append((score, entry, subnet))
        elif phase == "PUMPING":
            pumping.append((score, entry, subnet))
        elif phase == "COOLING":
            cooling.append((score, entry, subnet))

    alerts = _sort_bucket(early, _MAX_EARLY) + _sort_bucket(pumping, _MAX_PUMPING) + _sort_bucket(
        cooling, _MAX_COOLING
    )

    for alert in alerts:
        brief = {"move": alert["move"], "thesis": alert["thesis"]}
        if not hero_copy_is_clean(brief):
            alert["thesis"] = alert["thesis"].replace("audit gate", "bar")

    early_count = sum(1 for a in alerts if a.get("timing") == "lead")
    confirmed_count = sum(1 for a in alerts if a.get("timing") == "confirmed")
    count = early_count + confirmed_count
    status = "success" if count else "empty"
    return {
        "status": status,
        "count": count,
        "early_count": early_count,
        "confirmed_count": confirmed_count,
        "alerts": alerts,
        "empty_message": _EMPTY_MESSAGE,
        "error": None,
    }
