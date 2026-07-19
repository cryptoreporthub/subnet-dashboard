"""K3-6 — horizon selector views (Now / 24h / 7d) for dossier chips."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CHIP_LABELS = {"now": "Now", "24h": "24h", "7d": "7d"}
_STAGE_TITLES = {"now": "Hour pick", "24h": "24h call", "7d": "7d trend"}


def _conviction_pct(raw: Any) -> int:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return 0
    if 0.0 <= val <= 1.0:
        val *= 100.0
    return max(0, min(100, int(round(val))))


def _subnet_from_pick(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    sn = payload.get("subnet")
    if isinstance(sn, dict) and sn.get("netuid") is not None:
        return sn
    for key in ("pick", "candidate"):
        block = payload.get(key)
        if not isinstance(block, dict):
            continue
        inner = block.get("subnet") if isinstance(block.get("subnet"), dict) else block
        if isinstance(inner, dict) and inner.get("netuid") is not None:
            return inner
    return None


def _conviction_from_payload(payload: Optional[Dict[str, Any]]) -> int:
    if not isinstance(payload, dict):
        return 0
    for key in ("final_confidence", "confidence"):
        if payload.get(key) is not None:
            return _conviction_pct(payload[key])
    block = payload.get("pick") if isinstance(payload.get("pick"), dict) else payload.get("candidate")
    if isinstance(block, dict):
        for key in ("final_confidence", "confidence", "conviction"):
            if block.get(key) is not None:
                return _conviction_pct(block[key])
    return 0


def _action_from_payload(payload: Optional[Dict[str, Any]]) -> str:
    if not isinstance(payload, dict):
        return "HOLD"
    act = payload.get("action")
    if act:
        return str(act).upper()
    block = payload.get("pick") if isinstance(payload.get("pick"), dict) else payload.get("candidate")
    if isinstance(block, dict) and block.get("action"):
        return str(block["action"]).upper()
    return "HOLD"


def _subnet_row(subnets: List[Dict[str, Any]], netuid: Optional[int]) -> Optional[Dict[str, Any]]:
    if netuid is None:
        return None
    for row in subnets:
        if row.get("netuid") == netuid:
            return row
    return None


def _trend_lens_confidence(base_pct: int, pct_7d: Optional[float], action: str) -> Optional[int]:
    if pct_7d is None:
        return None
    act = (action or "HOLD").upper()
    if act in ("LONG", "BUY"):
        delta = int(round(pct_7d / 6))
    elif act in ("SHORT", "SELL"):
        delta = int(round(-pct_7d / 6))
    else:
        delta = int(round(abs(pct_7d) / 12))
    delta = max(-12, min(12, delta))
    return max(0, min(100, base_pct + delta))


def _view_subnet(sn: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    from internal.subnet_names import canonical_subnet_display

    return canonical_subnet_display(sn)


def _subnet_display_name(sn: Optional[Dict[str, Any]]) -> str:
    if not isinstance(sn, dict):
        return "—"
    name = str(sn.get("name") or "").strip()
    netuid = sn.get("netuid")
    if name and not name.upper().startswith("SN") and netuid is not None:
        return name
    if name:
        return name
    if netuid is not None:
        return f"SN{netuid}"
    return "—"


def _stage_line(chip_id: str, sn: Optional[Dict[str, Any]], action: str, conviction: int) -> str:
    """Human line: stage + subnet + stance for horizon chip toggles."""
    title = _STAGE_TITLES.get(chip_id, chip_id)
    name = _subnet_display_name(sn)
    act = (action or "HOLD").upper()
    if act in ("LONG", "BUY"):
        stance = "LONG candidate"
    elif act in ("SHORT", "SELL"):
        stance = "REDUCE lean"
    else:
        stance = "HOLD candidate"
    pct = f" · {conviction}% conviction" if conviction > 0 else ""
    if chip_id == "7d":
        return f"{title} · {name}{pct} · not graded"
    return f"{title} · {name}{pct} · {stance}"


def _council_view(
    chip_id: str,
    *,
    lens: str,
    payload: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    sn = _subnet_from_pick(payload)
    view_sn = _view_subnet(sn)
    if not view_sn:
        return None
    conviction = _conviction_from_payload(payload)
    action = _action_from_payload(payload)
    return {
        "id": chip_id,
        "label": _CHIP_LABELS.get(chip_id, chip_id),
        "stage_title": _STAGE_TITLES.get(chip_id, chip_id),
        "stage_line": _stage_line(chip_id, view_sn, action, conviction),
        "lens": lens,
        "subnet": view_sn,
        "conviction": conviction,
        "action": action,
        "note": None,
    }


def build_horizon_views(
    day_payload: Optional[Dict[str, Any]],
    hour_payload: Optional[Dict[str, Any]],
    subnets: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build SSR horizon_views for dossier chips (honest-empty when thin)."""
    subnets = subnets or []
    views: Dict[str, Any] = {}
    chips: List[str] = []

    hour_view = _council_view("now", lens="council_hour", payload=hour_payload)
    if hour_view:
        views["now"] = hour_view
        chips.append("now")

    day_view = _council_view("24h", lens="council_day", payload=day_payload)
    if day_view:
        views["24h"] = day_view
        chips.append("24h")

    if day_view:
        sn = day_view.get("subnet") or {}
        row = _subnet_row(subnets, sn.get("netuid"))
        pct_7d = None
        if isinstance(row, dict):
            try:
                pct_7d = float(row.get("price_change_7d"))
            except (TypeError, ValueError):
                pct_7d = None
        base = int(day_view.get("conviction") or 0)
        trend_conf = _trend_lens_confidence(base, pct_7d, str(day_view.get("action") or "HOLD"))
        if trend_conf is not None:
            action_7d = str(day_view.get("action") or "HOLD")
            views["7d"] = {
                "id": "7d",
                "label": "7d",
                "stage_title": _STAGE_TITLES["7d"],
                "stage_line": _stage_line("7d", sn, action_7d, trend_conf),
                "lens": "trend",
                "subnet": dict(sn),
                "conviction": trend_conf,
                "action": day_view.get("action"),
                "pct_7d": round(pct_7d, 2),
                "note": "Trend lens — not graded",
            }
            chips.append("7d")

    default = "24h" if "24h" in views else (chips[0] if chips else "24h")
    return {
        "default": default,
        "anchor": "24h" if "24h" in views else default,
        "chips": chips,
        "views": views,
    }


def attach_horizon_views_to_daily_pick(
    daily_payload: Optional[Dict[str, Any]],
    subnets: Optional[List[Dict[str, Any]]] = None,
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    base = dict(daily_payload) if isinstance(daily_payload, dict) else {}
    hour_payload: Optional[Dict[str, Any]] = None
    try:
        from internal.council.hourly_pick import select_hourly_pick

        if subnets:
            hour_payload = select_hourly_pick(subnets, market_context or {})
    except Exception as exc:
        logger.warning("horizon hour pick failed: %s", exc)

    try:
        base["horizon_views"] = build_horizon_views(base, hour_payload, subnets)
        base["horizon_active"] = base["horizon_views"].get("default", "24h")
    except Exception as exc:
        logger.warning("horizon views attach failed: %s", exc)
        base["horizon_views"] = {"default": "24h", "anchor": "24h", "chips": [], "views": {}}
        base["horizon_active"] = "24h"
    return base
