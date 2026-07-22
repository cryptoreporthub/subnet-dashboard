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
_EARLY_PHASES = frozenset({"STIRRING", "ACCUMULATING"})
_BAD_NAME = re.compile(r"^(unknown|deprecated|none|snnone|unnamed)$", re.I)


def _lead_thresholds() -> Dict[str, float]:
    try:
        from internal.learning.pump_calibration import effective_lead_gates

        return effective_lead_gates()
    except Exception:
        return {
            "buy_ratio_min": 0.55,
            "volume_intensity_min": 0.22,
            "just_started_max_score": 0.72,
        }


def _resolve_name(
    ladder_entry: Dict[str, Any],
    subnet_row: Optional[Dict[str, Any]],
) -> str:
    netuid = ladder_entry.get("netuid")
    try:
        netuid_int = int(netuid) if netuid is not None else None
    except (TypeError, ValueError):
        netuid_int = None

    if netuid_int is None:
        return "subnet"

    # Prefer local registry / overrides over stale ladder or remote labels
    # (e.g. SN54 ladder "Yanez MIID" vs registry "WebGenieAI").
    try:
        from internal.subnet_names import _load_local_registry, _load_name_overrides

        override = _load_name_overrides().get(str(netuid_int))
        if override and not _BAD_NAME.match(str(override).strip()):
            return str(override).strip()
        local = _load_local_registry()
        item = local.get(str(netuid_int)) if isinstance(local, dict) else None
        if isinstance(item, dict):
            lname = item.get("name")
            if lname and not _BAD_NAME.match(str(lname).strip()):
                return str(lname).strip()
    except Exception:
        pass

    tmc_name = None
    for src in (subnet_row, ladder_entry):
        if not isinstance(src, dict):
            continue
        raw = src.get("name") or src.get("subnet_name")
        if raw and not _BAD_NAME.match(str(raw).strip()):
            tmc_name = str(raw).strip()
            break
    try:
        from internal.subnet_names import resolve_subnet_name

        resolved = resolve_subnet_name(netuid_int, tmc_name=tmc_name)
        if resolved and not _BAD_NAME.match(resolved):
            return resolved
    except Exception:
        pass
    return f"SN{netuid_int}"


def _subnet_row(netuid: int, subnets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for row in subnets:
        if row.get("netuid") == netuid:
            return row
    return None


def _lead_signals(
    subnet_row: Optional[Dict[str, Any]],
    ladder_entry: Dict[str, Any],
) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {}
    raw = ladder_entry.get("signal_snapshot")
    if isinstance(raw, dict):
        snapshot = dict(raw)
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
    triad = snapshot.get("triad")
    if not isinstance(triad, dict) and snapshot:
        from internal.pump.triad import compute_pump_triad

        triad = compute_pump_triad(snapshot)
    return {
        "buy_ratio": buy_ratio,
        "volume_intensity": volume_intensity,
        "snapshot": snapshot,
        "triad": triad if isinstance(triad, dict) else {},
    }


def _size_cliff_line(subnet_row: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(subnet_row, dict):
        return None
    try:
        from internal.subnets.impact import REFERENCE_TAO, impact_profile, impact_tier

        profile = impact_profile(subnet_row, tao_amount=REFERENCE_TAO)
        ref_pct = profile.get("ref_impact_pct")
        if ref_pct is None:
            return None
        tier = impact_tier(subnet_row)
        depth = {"small": "thin", "mid": "healthy", "large": "deep"}.get(tier, "unknown")
        if not profile.get("market_cap"):
            return None
        return f"{REFERENCE_TAO:.0f} τ ≈ {float(ref_pct):.2f}% of float · {depth}"
    except Exception:
        return None


def _triad_badge(phase: str, triad: Dict[str, Any], default_badge: str) -> str:
    """STRONG only when all three triad legs lit on lead phases."""
    if phase not in _EARLY_PHASES:
        return default_badge
    lit = int(triad.get("lit_count") or 0)
    if lit >= 3:
        return "STRONG"
    if lit >= 2 and phase == "ACCUMULATING":
        return default_badge
    return default_badge


def _lead_qualifies(buy_ratio: Optional[float], volume_intensity: Optional[float]) -> bool:
    if buy_ratio is None or volume_intensity is None:
        return False
    gates = _lead_thresholds()
    return (
        buy_ratio >= gates["buy_ratio_min"]
        and volume_intensity >= gates["volume_intensity_min"]
    )


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
    *,
    score: Optional[float] = None,
) -> Dict[str, str]:
    if phase == "STIRRING":
        br = buy_ratio if buy_ratio is not None else 0.5
        vi = volume_intensity if volume_intensity is not None else 0.0
        return {
            "move": _move_line("WATCH", name, netuid_int),
            "badge": "WARMING UP",
            "timing": "lead",
            "thesis": (
                f"Pump warming up — buy pressure building before price runs "
                f"({br:.0%} flow, vol {vi:.0%}). Watch for 2%+ in the next hour if flow holds."
            ),
            "trigger": "Early heads-up — small watch size or wait for BUILDING confirmation.",
        }
    if phase == "ACCUMULATING":
        br = buy_ratio if buy_ratio is not None else 0.5
        vi = volume_intensity if volume_intensity is not None else 0.0
        return {
            "move": _move_line("BUILDING", name, netuid_int),
            "badge": "BUILDING",
            "timing": "lead",
            "thesis": (
                f"Flow and volume aligning — high chance of 2%+ soon if buyers hold "
                f"({br:.0%} buys, vol {vi:.0%})."
            ),
            "trigger": "Best entry band — act before JUST STARTED or you only get a partial move.",
        }
    if phase == "PUMPING":
        just_max = _lead_thresholds()["just_started_max_score"]
        br = buy_ratio if buy_ratio is not None else 0.5
        vi = volume_intensity if volume_intensity is not None else 0.0
        sc = score if score is not None else 0.0
        label = _display_label(name, netuid_int)
        if score is not None and score < just_max:
            return {
                "move": _move_line("LIVE", name, netuid_int),
                "badge": "JUST STARTED",
                "timing": "confirmed",
                "thesis": (
                    f"{label} just confirmed (score {sc:.2f}, {br:.0%} buys, vol {vi:.0%}) — "
                    f"missed the first leg but entry still has room; size down."
                ),
                "trigger": (
                    f"Not early on {label} — smaller position or wait for the next BUILDING name."
                ),
            }
        return {
            "move": _move_line("CONFIRMED", name, netuid_int),
            "badge": "CHASE RISK",
            "timing": "confirmed",
            "thesis": (
                f"{label} is live at score {sc:.2f} ({br:.0%} buys, vol {vi:.0%}) — "
                f"you are not early. Use for exit sizing and rotation, not fresh entry."
            ),
            "trigger": (
                f"Do not chase {label}; trim on EXIT WATCH or rotate to BUILDING names."
            ),
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


def _wallet_chip(netuid_int: Optional[int]) -> Optional[str]:
    """Lead-wallet chip — honest-empty when no whale data."""
    if netuid_int is None:
        return None
    try:
        from internal.whales.service import WhaleIntelligenceService

        flow = WhaleIntelligenceService().get_subnet_flow(netuid_int)
        if not flow.get("data_available"):
            return None
        by_class = flow.get("by_classification") if isinstance(flow.get("by_classification"), dict) else {}
        early = by_class.get("early_movers") or []
        alpha = by_class.get("alpha_whales") or []
        n = len(early) + len(alpha)
        if n > 0:
            return f"{n} wallet{'s' if n != 1 else ''} bought before move"
        if flow.get("smart_money_present"):
            return "Smart money in"
    except Exception:
        return None
    return None


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
    triad = leads.get("triad") or {}
    try:
        score = float(ladder_entry.get("composite_score") or 0.0)
    except (TypeError, ValueError):
        score = None
    copy = _row_copy(
        phase,
        name,
        leads["buy_ratio"],
        leads["volume_intensity"],
        netuid_int,
        score=score,
    )
    badge = _triad_badge(phase, triad, copy["badge"])
    if badge == "STRONG" and phase == "ACCUMULATING":
        copy["badge"] = "STRONG"
        copy["thesis"] = (
            f"Full triad — inflow, pressure, and coil aligned. "
            f"High chance of 2%+ soon if buyers hold "
            f"({leads['buy_ratio']:.0%} buys, vol {leads['volume_intensity']:.0%})."
            if leads["buy_ratio"] is not None and leads["volume_intensity"] is not None
            else "Full triad — inflow, pressure, and coil aligned."
        )
    elif badge == "STRONG" and phase == "STIRRING":
        copy["badge"] = "STRONG"
    else:
        copy["badge"] = badge

    size_line = _size_cliff_line(subnet_row)
    wallet_chip = _wallet_chip(netuid_int)
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
        "triad": triad,
        "size_line": size_line,
        "wallet_chip": wallet_chip,
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
            "trust": {
                "ready": False,
                "line": "Early alerts: grading starts once lead phase entries resolve (1h).",
            },
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
    try:
        from internal.learning.pump_lead_stats import build_pump_desk_trust

        trust = build_pump_desk_trust()
    except Exception:
        trust = {
            "ready": False,
            "line": "Early alerts: grading starts once lead phase entries resolve (1h).",
        }
    return {
        "status": status,
        "count": count,
        "early_count": early_count,
        "confirmed_count": confirmed_count,
        "alerts": alerts,
        "empty_message": _EMPTY_MESSAGE,
        "error": None,
        "trust": trust,
    }
