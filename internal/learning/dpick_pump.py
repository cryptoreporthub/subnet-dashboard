"""K3-7b dossier pump chip — STIRRING/ACCUMULATING, lead-signal gated."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Leading flow/volume only — not price lag (momentum_1h, price_change_24h).
_LEAD_BUY_RATIO_MIN = 0.55
_LEAD_VOLUME_INTENSITY_MIN = 0.22

_DISPLAY_PHASES = frozenset({"STIRRING", "ACCUMULATING"})


def _empty_chip() -> Dict[str, Any]:
    return {
        "show": False,
        "tier": "",
        "label": "",
        "trigger": "",
        "buy_ratio": None,
        "volume_intensity": None,
    }


def _hero_netuid(payload: Dict[str, Any]) -> Optional[int]:
    pick = payload.get("pick")
    if isinstance(pick, dict) and isinstance(pick.get("subnet"), dict):
        netuid = pick["subnet"].get("netuid")
        if netuid is not None:
            return int(netuid)
    cand = payload.get("candidate")
    if isinstance(cand, dict) and isinstance(cand.get("subnet"), dict):
        netuid = cand["subnet"].get("netuid")
        if netuid is not None:
            return int(netuid)
    return None


def _subnet_row(netuid: int, subnets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for row in subnets:
        if row.get("netuid") == netuid:
            return row
    return None


def _lead_signals(
    subnet_row: Optional[Dict[str, Any]],
    ladder_entry: Optional[Dict[str, Any]],
) -> Dict[str, float]:
    snapshot = {}
    if isinstance(ladder_entry, dict):
        raw = ladder_entry.get("signal_snapshot")
        if isinstance(raw, dict):
            snapshot = raw
    if not snapshot and isinstance(subnet_row, dict):
        from internal.pump.signals import build_subnet_signals

        snapshot = build_subnet_signals(subnet_row)
    try:
        buy_ratio = float(snapshot.get("buy_ratio", 0.5))
    except (TypeError, ValueError):
        buy_ratio = 0.5
    try:
        volume_intensity = float(snapshot.get("volume_intensity", 0.0))
    except (TypeError, ValueError):
        volume_intensity = 0.0
    return {"buy_ratio": buy_ratio, "volume_intensity": volume_intensity}


def _chip_copy(phase: str, buy_ratio: float, volume_intensity: float) -> Dict[str, str]:
    if phase == "ACCUMULATING":
        return {
            "label": "HEAT BUILDING",
            "trigger": (
                "Buy flow and volume aligned — ladder heating before price chase. "
                f"Flow {buy_ratio:.0%} buy · vol {volume_intensity:.0%}."
            ),
        }
    return {
        "label": "EARLY HEAT",
        "trigger": (
            "Early buy pressure building — volume still warming, not a chase signal. "
            f"Flow {buy_ratio:.0%} buy · vol {volume_intensity:.0%}."
        ),
    }


def build_pump_chip(
    netuid: Optional[int],
    subnet_row: Optional[Dict[str, Any]] = None,
    *,
    ladder_entry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return dossier pump chip when phase + lead signals qualify."""
    empty = _empty_chip()
    if netuid is None:
        return empty

    if ladder_entry is None:
        from internal.pump.state import load_state

        ladder_entry = (load_state().get("subnets") or {}).get(str(netuid))
    if not isinstance(ladder_entry, dict):
        return empty

    phase = str(ladder_entry.get("phase") or "DORMANT").upper()
    if phase not in _DISPLAY_PHASES:
        return empty

    leads = _lead_signals(subnet_row, ladder_entry)
    buy_ratio = leads["buy_ratio"]
    volume_intensity = leads["volume_intensity"]
    if buy_ratio < _LEAD_BUY_RATIO_MIN or volume_intensity < _LEAD_VOLUME_INTENSITY_MIN:
        return empty

    copy = _chip_copy(phase, buy_ratio, volume_intensity)
    return {
        "show": True,
        "tier": phase,
        "label": copy["label"],
        "trigger": copy["trigger"],
        "buy_ratio": round(buy_ratio, 4),
        "volume_intensity": round(volume_intensity, 4),
    }


def attach_pump_chip_to_daily_pick(
    payload: Optional[Dict[str, Any]],
    subnets: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    base = dict(payload) if isinstance(payload, dict) else {}
    if isinstance(base.get("pump_chip"), dict) and base["pump_chip"].get("show"):
        return base
    rows = subnets if isinstance(subnets, list) else []
    netuid = _hero_netuid(base)
    row = _subnet_row(netuid, rows) if netuid is not None else None
    base["pump_chip"] = build_pump_chip(netuid, row)
    return base
