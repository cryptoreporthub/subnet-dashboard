"""K3-8b Pump lane — predictive lead scanner (flow before price)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from internal.learning.dpick_copy import hero_copy_is_clean

_EMPTY_MESSAGE = (
    "No lead or confirmed motion right now. Early heat on today's pick stays on the "
    "dossier chip when flow warms."
)
_MAX_EARLY = 5
_MAX_PUMPING = 3
_MAX_COOLING = 2
_MAX_WATCH = 5
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


def _label_hint(*sources: Optional[Dict[str, Any]]) -> Optional[str]:
    for src in sources:
        if not isinstance(src, dict):
            continue
        raw = src.get("name") or src.get("subnet_name")
        if not raw:
            continue
        label = str(raw).strip()
        if _BAD_NAME.match(label):
            continue
        if re.match(r"^SN\d+$", label, re.I):
            continue
        return label
    return None


def _resolve_name(
    ladder_entry: Dict[str, Any],
    subnet_row: Optional[Dict[str, Any]],
) -> str:
    """Display name for a pump desk card (override → TMC → registry → live hint)."""
    netuid = ladder_entry.get("netuid")
    try:
        netuid_int = int(netuid) if netuid is not None else None
    except (TypeError, ValueError):
        netuid_int = None

    if netuid_int is None:
        return "subnet"

    try:
        from internal.subnet_names import display_name_for_netuid

        ladder_hint = _label_hint(ladder_entry)
        return display_name_for_netuid(
            netuid_int,
            subnet_row=subnet_row,
            ladder_hint=ladder_hint,
            use_taostats_fallback=True,
        )
    except Exception:
        pass
    return f"SN{netuid_int}"


def _subnet_row(netuid: int, subnets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for row in subnets:
        if row.get("netuid") == netuid:
            return row
    return None


def _signal_snapshot_stale(snapshot: Dict[str, Any]) -> bool:
    """Detect placeholder ladder snapshots (0.5 buys / 100% vol) from missing flow fields."""
    if not snapshot:
        return True
    try:
        buy_ratio = float(snapshot.get("buy_ratio", 0.5))
        volume_intensity = float(snapshot.get("volume_intensity", 0.0))
    except (TypeError, ValueError):
        return True
    if abs(buy_ratio - 0.5) > 1e-6:
        return False
    # ponytail: Fly volume rows froze 0.5/1.0 when buy/sell flow was absent
    return volume_intensity >= 0.99 or volume_intensity <= 0.0


def _lead_signals(
    subnet_row: Optional[Dict[str, Any]],
    ladder_entry: Dict[str, Any],
) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {}
    raw = ladder_entry.get("signal_snapshot")
    if isinstance(raw, dict):
        snapshot = dict(raw)
    if isinstance(subnet_row, dict) and (not snapshot or _signal_snapshot_stale(snapshot)):
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


def _human_updated_ago(updated_at: Optional[str]) -> str:
    if not updated_at:
        return ""
    try:
        ts = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
    except ValueError:
        return ""
    age = int((datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds())
    if age < 60:
        return "just now"
    if age < 3600:
        return f"{age // 60}m ago"
    if age < 86400:
        return f"{age // 3600}h ago"
    return f"{age // 86400}d ago"


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


def _watch_row_copy(
    name: str,
    buy_ratio: Optional[float],
    volume_intensity: Optional[float],
    netuid_int: Optional[int],
) -> Dict[str, str]:
    gates = _lead_thresholds()
    br_min = float(gates["buy_ratio_min"])
    vi_min = float(gates["volume_intensity_min"])
    br = buy_ratio if buy_ratio is not None else 0.5
    vi = volume_intensity if volume_intensity is not None else 0.0
    gaps: List[str] = []
    if br < br_min:
        gaps.append(f"buy flow {br:.0%} (need {br_min:.0%})")
    if vi < vi_min:
        gaps.append(f"vol {vi:.0%} (need {vi_min:.0%})")
    gap_txt = "; ".join(gaps) if gaps else "flow below lead gate"
    return {
        "move": _move_line("RADAR", name, netuid_int),
        "badge": "NEAR GATE",
        "timing": "watch",
        "thesis": (
            f"STIRRING on ladder but below lead gate — {gap_txt}. "
            "Not a lead alert; watch the dossier if flow ticks up."
        ),
        "trigger": "Desk stays quiet until buy ratio and volume clear the gate.",
    }


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
    return whale_intel_line(netuid_int).get("wallet_chip")


_whale_service_singleton: Any = None


def _whale_service():
    global _whale_service_singleton
    if _whale_service_singleton is None:
        from internal.whales.service import WhaleIntelligenceService

        _whale_service_singleton = WhaleIntelligenceService()
    return _whale_service_singleton


def whale_intel_line(netuid_int: Optional[int]) -> Dict[str, Optional[str]]:
    """Whale accumulation one-liner for desk cards and push alerts."""
    out: Dict[str, Optional[str]] = {"wallet_chip": None, "whale_archetype": None}
    if netuid_int is None:
        return out
    try:
        flow = _whale_service().get_subnet_flow(netuid_int)
        if not flow.get("data_available"):
            return out
        by_class = flow.get("by_classification") if isinstance(flow.get("by_classification"), dict) else {}
        alpha = len(by_class.get("alpha_whales") or [])
        early = len(by_class.get("early_movers") or [])
        conviction = len(by_class.get("conviction_holders") or [])
        ruggers = len(by_class.get("ruggers") or [])
        n_smart = alpha + early + conviction

        if flow.get("avoid_follow") or (ruggers and not n_smart):
            out["wallet_chip"] = "Rugger wallets active — caution"
            out["whale_archetype"] = "Rug risk"
            return out

        if n_smart > 0:
            out["wallet_chip"] = f"{n_smart} whale wallet{'s' if n_smart != 1 else ''} accumulating"
            if alpha and early:
                out["whale_archetype"] = "Smart money accumulation"
            elif alpha:
                out["whale_archetype"] = "Alpha whale accumulation"
            elif early:
                out["whale_archetype"] = "Early mover accumulation"
            else:
                out["whale_archetype"] = "Conviction holder accumulation"
            return out

        if flow.get("smart_money_present"):
            out["wallet_chip"] = "Smart money in"
            out["whale_archetype"] = "Smart money"
            return out

        open_pos = int(flow.get("open_positions") or 0)
        if open_pos > 0:
            out["wallet_chip"] = f"{open_pos} whale position{'s' if open_pos != 1 else ''} open"
            out["whale_archetype"] = "Whale interest"
    except Exception:
        pass
    return out


def public_subnet_url(netuid: int) -> str:
    import os

    base = os.environ.get("PUBLIC_APP_URL", "https://subnet-dashboard.fly.dev").rstrip("/")
    return f"{base}/subnet/{int(netuid)}"


def format_pump_phase_alert(
    *,
    netuid: int,
    name: Optional[str],
    badge: str,
    phase: str,
    signal_snapshot: Optional[Dict[str, Any]] = None,
    composite_score: Optional[float] = None,
) -> str:
    """Rich Telegram push body for BUILDING / JUST STARTED entries."""
    label = name or f"SN{netuid}"
    badge_u = str(badge or "").upper()
    lines = [f"🔥 Pump desk · {badge_u}", f"{label} SN{netuid}"]

    whale = whale_intel_line(int(netuid))
    if whale.get("wallet_chip"):
        lines.append(f"→ {whale['wallet_chip']}")
    if whale.get("whale_archetype"):
        lines.append(f"→ {whale['whale_archetype']}")

    snap = signal_snapshot if isinstance(signal_snapshot, dict) else {}
    try:
        buy_pct = int(round(float(snap.get("buy_ratio", 0)) * 100))
        if buy_pct > 0:
            lines.append(f"→ Buy pressure {buy_pct}%")
    except (TypeError, ValueError):
        pass
    try:
        vol_pct = int(round(float(snap.get("volume_intensity", 0)) * 100))
        if vol_pct > 0:
            lines.append(f"→ Volume intensity {vol_pct}%")
    except (TypeError, ValueError):
        pass
    if composite_score is not None:
        try:
            setup_pct = int(round(float(composite_score) * 100))
            lines.append(f"→ Setup index {setup_pct}%")
        except (TypeError, ValueError):
            pass

    tg = _telegram_chip({"signal_snapshot": snap})
    if tg:
        lines.append(f"→ {tg}")

    phase_u = str(phase or "").upper()
    if badge_u == "BUILDING":
        lines.append("Bullish setup — act before JUST STARTED.")
    elif badge_u == "JUST STARTED":
        lines.append("Move confirmed — size down; not early entry.")
    else:
        lines.append(f"Phase {phase_u or 'active'}.")

    lines.append(public_subnet_url(int(netuid)))
    return "\n".join(lines)


def _telegram_chip(ladder_entry: Dict[str, Any]) -> Optional[str]:
    """Surface Telegram chatter intensity already baked into signal_snapshot."""
    snap = ladder_entry.get("signal_snapshot") if isinstance(ladder_entry.get("signal_snapshot"), dict) else {}
    try:
        chatter = float(snap.get("chatter_intensity") or 0)
    except (TypeError, ValueError):
        return None
    if chatter < 0.15:
        return None
    if chatter >= 0.65:
        return f"Telegram hot · {chatter:.0%}"
    if chatter >= 0.35:
        return f"Telegram warming · {chatter:.0%}"
    return f"Telegram chatter · {chatter:.0%}"


def _abbrev_coldkey(addr: str) -> str:
    s = str(addr).strip()
    if len(s) <= 12:
        return s
    return f"{s[:4]}…{s[-4:]}"


def _owner_chip(
    netuid_int: Optional[int],
    subnet_row: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Subnet owner coldkey from registry / subnet row — honest-empty when unknown."""
    owner = None
    if isinstance(subnet_row, dict):
        owner = subnet_row.get("owner") or subnet_row.get("owner_coldkey")
    if not owner and netuid_int is not None:
        try:
            from internal.subnet_names import _load_local_registry

            item = _load_local_registry().get(str(netuid_int))
            if isinstance(item, dict):
                owner = item.get("owner")
        except Exception:
            owner = None
    if not owner:
        return None
    addr = str(owner).strip()
    if len(addr) < 8:
        return None
    return f"Owner {_abbrev_coldkey(addr)}"


def _whale_day_chips(
    netuid_int: Optional[int],
    subnet_row: Optional[Dict[str, Any]],
) -> List[str]:
    """Biggest TAO tx + largest slip-proxy move today — card chips, no new section."""
    if netuid_int is None:
        return []
    try:
        from internal.subnets.impact import subnet_market_cap
        from internal.whales.service import WhaleIntelligenceService

        liq = 0.0
        if isinstance(subnet_row, dict):
            liq = float(subnet_market_cap(subnet_row) or 0)
            if liq <= 0:
                for key in ("liquidity", "liquidity_tao", "total_stake", "total_stake_tao"):
                    try:
                        v = float(subnet_row.get(key) or 0)
                    except (TypeError, ValueError):
                        continue
                    if v > 0:
                        liq = v
                        break
        highlights = WhaleIntelligenceService().day_move_highlights(
            netuid_int,
            liquidity_tao=liq if liq > 0 else None,
            hours=24.0,
        )
        chips = highlights.get("chips") if isinstance(highlights, dict) else None
        if isinstance(chips, list):
            return [str(c) for c in chips if c]
    except Exception:
        return []
    return []


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
    try:
        accum = float(ladder_entry.get("accum_score")) if ladder_entry.get("accum_score") is not None else None
    except (TypeError, ValueError):
        accum = None
    try:
        confirm = float(ladder_entry.get("confirm_score")) if ladder_entry.get("confirm_score") is not None else None
    except (TypeError, ValueError):
        confirm = None
    try:
        from internal.pump.two_score import score_layer_for_phase

        layer = str(ladder_entry.get("score_layer") or score_layer_for_phase(phase))
    except Exception:
        layer = "none"
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
    owner_chip = _owner_chip(netuid_int, subnet_row)
    telegram_chip = _telegram_chip(ladder_entry)
    day_chips = _whale_day_chips(netuid_int, subnet_row)
    snap = ladder_entry.get("signal_snapshot") if isinstance(ladder_entry.get("signal_snapshot"), dict) else {}
    src = subnet_row if isinstance(subnet_row, dict) else {}

    def _metric(*keys, default=None):
        for k in keys:
            for bag in (src, snap, ladder_entry):
                if isinstance(bag, dict) and bag.get(k) is not None:
                    return bag.get(k)
        return default

    try:
        fear = float(_metric("fear_and_greed", default=0) or 0)
    except (TypeError, ValueError):
        fear = None
    try:
        buys = int(_metric("buys_24hr", default=0) or 0)
    except (TypeError, ValueError):
        buys = None
    try:
        sells = int(_metric("sells_24hr", default=0) or 0)
    except (TypeError, ValueError):
        sells = None
    try:
        buy_vol = float(_metric("buy_volume_24h", default=0) or 0)
    except (TypeError, ValueError):
        buy_vol = None
    try:
        sell_vol = float(_metric("sell_volume_24h", default=0) or 0)
    except (TypeError, ValueError):
        sell_vol = None

    spark_closes: List[float] = []
    if isinstance(subnet_row, dict):
        try:
            from internal.analytics.root_context import spark_closes_cached_only

            spark_closes = spark_closes_cached_only(subnet_row)
        except Exception:
            spark_closes = []

    row = {
        "netuid": netuid_int,
        "name": name,
        "phase": phase,
        "timing": copy["timing"],
        "score": round(score, 2) if score is not None else None,
        "accum_score": round(accum, 2) if accum is not None else None,
        "confirm_score": round(confirm, 2) if confirm is not None else None,
        "score_layer": layer,
        "alert_id": ladder_entry.get("alert_id"),
        "move": copy["move"],
        "thesis": copy["thesis"],
        "trigger": copy["trigger"],
        "badge": copy["badge"],
        "buy_ratio": leads["buy_ratio"],
        "volume_intensity": leads["volume_intensity"],
        "triad": triad,
        "size_line": size_line,
        "wallet_chip": wallet_chip,
        "owner_chip": owner_chip,
        "telegram_chip": telegram_chip,
        "whale_day_chips": day_chips,
        "fear_and_greed": fear,
        "buys_24hr": buys,
        "sells_24hr": sells,
        "buy_volume_24h": buy_vol,
        "sell_volume_24h": sell_vol,
        "price_change_24h": _metric("price_change_24h"),
        "price_change_1h": _metric("price_change_1h", "change_1h"),
        "spark_closes": spark_closes,
        "taostats_wired": bool(
            src.get("taostats_wired")
            or snap.get("taostats_wired")
            or (isinstance(src.get("sources"), list) and "taostats" in src.get("sources"))
        ),
        "updated_at": ladder_entry.get("updated_at"),
    }
    return row


def _sort_bucket(
    entries: List[Tuple[float, Dict[str, Any], Optional[Dict[str, Any]]]],
    limit: int,
    *,
    row_builder=build_alert_row,
) -> List[Dict[str, Any]]:
    entries.sort(key=lambda t: t[0], reverse=True)
    return [row_builder(entry, row) for _, entry, row in entries[:limit]]


def _snapshot_lead_signals(ladder_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Ladder-only lead metrics — no live subnet signal rebuild (hot API path)."""
    snapshot: Dict[str, Any] = {}
    raw = ladder_entry.get("signal_snapshot")
    if isinstance(raw, dict):
        snapshot = dict(raw)
    try:
        buy_ratio = float(snapshot.get("buy_ratio", 0.5))
    except (TypeError, ValueError):
        buy_ratio = None
    try:
        volume_intensity = float(snapshot.get("volume_intensity", 0.0))
    except (TypeError, ValueError):
        volume_intensity = None
    return {"buy_ratio": buy_ratio, "volume_intensity": volume_intensity}


_HERO_SUBTITLES = {
    "WARMING UP": "Early flow building before price runs",
    "BUILDING": "Momentum breakout forming",
    "STRONG": "Full triad aligned — act band",
    "JUST STARTED": "Move just confirmed on ladder",
    "CHASE RISK": "Late leg — size down only",
    "FADING": "Cooling — exit watch",
}


def _desk_metrics(
    ladder_entry: Dict[str, Any],
    leads: Dict[str, Any],
    score: Optional[float],
) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {}
    raw = ladder_entry.get("signal_snapshot")
    if isinstance(raw, dict):
        snapshot = dict(raw)
    try:
        from internal.pump.triad import compute_pump_triad

        triad = compute_pump_triad(snapshot) if snapshot else compute_pump_triad({})
    except Exception:
        triad = {"inflow_quiet_load": False, "buy_pressure": False, "price_coil": False, "lit_count": 0}
    sc = float(score or 0.0)
    try:
        accum = float(ladder_entry.get("accum_score")) if ladder_entry.get("accum_score") is not None else sc
    except (TypeError, ValueError):
        accum = sc
    try:
        confirm = float(ladder_entry.get("confirm_score")) if ladder_entry.get("confirm_score") is not None else sc
    except (TypeError, ValueError):
        confirm = sc
    gates = _lead_thresholds()
    trigger = float(gates.get("just_started_max_score", 0.72))
    distance = round(max(0.0, trigger - sc), 2)
    return {
        "formation_pct": min(100, int(round(accum * 100))),
        "confirm_pct": min(100, int(round(confirm * 100))),
        "momentum_pct": min(100, int(round(confirm * 100))),
        "distance": distance,
        "trigger_score": trigger,
        "triad": triad,
    }


def _progress_series_from_trail(
    ladder_entry: Dict[str, Any],
    score: Optional[float],
    trigger: float,
) -> List[int]:
    """Score ÷ trigger as % — honest trail from ladder scans; last point = live progress."""
    trigger = max(float(trigger), 1e-9)
    trail = ladder_entry.get("score_trail")
    scores: List[float] = []
    if isinstance(trail, list):
        for raw in trail:
            try:
                scores.append(float(raw))
            except (TypeError, ValueError):
                continue
    if len(scores) < 2 and score is not None:
        progress = int(round(float(score) / trigger * 100))
        return [progress, progress]
    if len(scores) < 2:
        return []
    return [int(round(s / trigger * 100)) for s in scores]


def _triad_pill_labels(triad: Dict[str, Any]) -> Dict[str, str]:
    inflow_on = bool(triad.get("inflow_quiet_load"))
    pressure_on = bool(triad.get("buy_pressure"))
    coil_on = bool(triad.get("price_coil"))
    return {
        "inflow": "STRONG" if inflow_on else "WATCH",
        "pressure": "RISING" if pressure_on else "FLAT",
        "coil": "TIGHT" if coil_on else "OPEN",
    }


def build_desk_row(
    ladder_entry: Dict[str, Any],
    subnet_row: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Minimal pump desk row — names, timing, formation %, cached sparklines only."""
    phase = str(ladder_entry.get("phase") or "DORMANT").upper()
    netuid = ladder_entry.get("netuid")
    try:
        netuid_int = int(netuid) if netuid is not None else None
    except (TypeError, ValueError):
        netuid_int = None
    name = _resolve_name(ladder_entry, subnet_row)
    leads = _snapshot_lead_signals(ladder_entry)
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
    metrics = _desk_metrics(ladder_entry, leads, score)
    triad = metrics.get("triad") or {}
    pills = _triad_pill_labels(triad if isinstance(triad, dict) else {})
    subtitle = _HERO_SUBTITLES.get(copy["badge"], copy["badge"])
    spark_closes: List[float] = []
    if isinstance(subnet_row, dict):
        try:
            from internal.analytics.root_context import spark_closes_cached_only

            spark_closes = spark_closes_cached_only(subnet_row)
        except Exception:
            spark_closes = []
    corr = _progress_series_from_trail(
        ladder_entry,
        score,
        metrics["trigger_score"],
    )
    # ponytail: one whale-service load per request; in-memory scan per netuid is cheap.
    whale = whale_intel_line(netuid_int)
    wallet_chip = whale.get("wallet_chip")
    whale_archetype = whale.get("whale_archetype")
    size_line = _size_cliff_line(subnet_row)
    owner_chip = _owner_chip(netuid_int, subnet_row)
    telegram_chip = _telegram_chip(ladder_entry)
    lit = int(triad.get("lit_count") or 0) if isinstance(triad, dict) else 0
    buy_pct = int(round(leads["buy_ratio"] * 100)) if leads.get("buy_ratio") is not None else None
    vol_pct = (
        int(round(leads["volume_intensity"] * 100)) if leads.get("volume_intensity") is not None else None
    )
    pattern_class = None
    pattern_label = None
    pattern_highlight = False
    if netuid_int is not None:
        try:
            from internal.pump.pattern_ledger import pattern_payload

            pat = pattern_payload(netuid_int)
            pattern_class = pat.get("pattern_class")
            pattern_label = pat.get("pattern_label") or pat.get("waveform")
            if pattern_class in {"PUMP_DROP_RE_PUMP", "FLAT_COIL"} and phase in {
                "STIRRING",
                "ACCUMULATING",
            }:
                pattern_highlight = True
        except Exception:
            pass
    return {
        "netuid": netuid_int,
        "name": name,
        "phase": phase,
        "timing": copy["timing"],
        "score": round(score, 2) if score is not None else None,
        "badge": copy["badge"],
        "spark_closes": spark_closes,
        "progress_series": corr,
        "move": copy["move"],
        "thesis": copy["thesis"],
        "trigger": copy["trigger"],
        "subtitle": subtitle,
        "formation_pct": metrics["formation_pct"],
        "confirm_pct": metrics["confirm_pct"],
        "momentum_pct": metrics["momentum_pct"],
        "distance": metrics["distance"],
        "trigger_score": metrics["trigger_score"],
        "triad": triad,
        "triad_labels": pills,
        "triad_lit": lit,
        "size_line": size_line,
        "owner_chip": owner_chip,
        "telegram_chip": telegram_chip,
        "wallet_chip": wallet_chip,
        "whale_archetype": whale_archetype,
        "buy_pct": buy_pct,
        "vol_pct": vol_pct,
        "updated_at": ladder_entry.get("updated_at"),
        "updated_ago": _human_updated_ago(ladder_entry.get("updated_at")),
        "pattern_class": pattern_class,
        "pattern_label": pattern_label,
        "pattern_highlight": pattern_highlight,
    }


def build_watch_row(
    ladder_entry: Dict[str, Any],
    subnet_row: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """STIRRING below lead gate — honest radar row when the desk has no leads."""
    row = build_desk_row(ladder_entry, subnet_row)
    leads = _snapshot_lead_signals(ladder_entry)
    copy = _watch_row_copy(row["name"], leads["buy_ratio"], leads["volume_intensity"], row["netuid"])
    row.update(
        {
            "timing": "watch",
            "badge": copy["badge"],
            "move": copy["move"],
            "thesis": copy["thesis"],
            "trigger": copy["trigger"],
            "subtitle": "Below lead gate — radar only",
        }
    )
    return row


def _collect_almost_warming(
    state: Dict[str, Any],
    subnets: List[Dict[str, Any]],
) -> List[Tuple[float, Dict[str, Any], Optional[Dict[str, Any]]]]:
    """STIRRING names on the ladder that have not cleared buy/vol lead gates."""
    out: List[Tuple[float, Dict[str, Any], Optional[Dict[str, Any]]]] = []
    for entry in (state.get("subnets") or {}).values():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("phase") or "").upper() != "STIRRING":
            continue
        netuid = entry.get("netuid")
        subnet = _subnet_row(int(netuid), subnets) if netuid is not None else None
        leads = _snapshot_lead_signals(entry)
        if _lead_qualifies(leads["buy_ratio"], leads["volume_intensity"]):
            continue
        score = float(entry.get("composite_score") or 0.0)
        try:
            rank = float(entry.get("accum_score")) if entry.get("accum_score") is not None else score
        except (TypeError, ValueError):
            rank = score
        out.append((rank, entry, subnet))
    return out


def _attach_watch_when_empty(
    payload: Dict[str, Any],
    state: Dict[str, Any],
    subnets: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if payload.get("status") != "empty" or payload.get("count"):
        return payload
    almost = _collect_almost_warming(state, subnets)
    if not almost:
        return payload
    watch = _sort_bucket(almost, _MAX_WATCH, row_builder=build_watch_row)
    payload["watch"] = watch
    payload["watch_count"] = len(watch)
    return payload


def _collect_pump_buckets(
    state: Dict[str, Any],
    subnets: List[Dict[str, Any]],
    *,
    desk: bool = False,
) -> Tuple[
    List[Tuple[float, Dict[str, Any], Optional[Dict[str, Any]]]],
    List[Tuple[float, Dict[str, Any], Optional[Dict[str, Any]]]],
    List[Tuple[float, Dict[str, Any], Optional[Dict[str, Any]]]],
]:
    early: List[Tuple[float, Dict[str, Any], Optional[Dict[str, Any]]]] = []
    pumping: List[Tuple[float, Dict[str, Any], Optional[Dict[str, Any]]]] = []
    cooling: List[Tuple[float, Dict[str, Any], Optional[Dict[str, Any]]]] = []

    for entry in (state.get("subnets") or {}).values():
        if not isinstance(entry, dict):
            continue
        phase = str(entry.get("phase") or "").upper()
        netuid = entry.get("netuid")
        subnet = _subnet_row(int(netuid), subnets) if netuid is not None else None
        score = float(entry.get("composite_score") or 0.0)
        try:
            rank = float(entry.get("accum_score")) if entry.get("accum_score") is not None else score
        except (TypeError, ValueError):
            rank = score
        if phase in _EARLY_PHASES:
            leads = _snapshot_lead_signals(entry) if desk else _lead_signals(subnet, entry)
            if phase == "ACCUMULATING" or _lead_qualifies(
                leads["buy_ratio"], leads["volume_intensity"]
            ):
                early.append((rank, entry, subnet))
        elif phase == "PUMPING":
            try:
                conf_rank = (
                    float(entry.get("confirm_score"))
                    if entry.get("confirm_score") is not None
                    else score
                )
            except (TypeError, ValueError):
                conf_rank = score
            pumping.append((conf_rank, entry, subnet))
        elif phase == "COOLING":
            cooling.append((score, entry, subnet))
    return early, pumping, cooling


def _finalize_pump_payload(
    alerts: List[Dict[str, Any]],
    *,
    desk: bool,
) -> Dict[str, Any]:
    for alert in alerts:
        brief = {"move": alert["move"], "thesis": alert["thesis"]}
        if not hero_copy_is_clean(brief):
            alert["thesis"] = alert["thesis"].replace("audit gate", "bar")

    early_count = sum(1 for a in alerts if a.get("timing") == "lead")
    confirmed_count = sum(1 for a in alerts if a.get("timing") == "confirmed")
    exit_count = sum(1 for a in alerts if a.get("timing") == "exit")
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
    payload = {
        "status": status,
        "count": count,
        "early_count": early_count,
        "confirmed_count": confirmed_count,
        "exit_count": exit_count,
        "alerts": alerts,
        "empty_message": _EMPTY_MESSAGE,
        "error": None,
        "trust": trust,
        "desk": desk,
    }
    if desk and alerts:
        hero = next((a for a in alerts if a.get("timing") == "lead"), alerts[0])
        payload["hero"] = hero
    return payload


def _pump_subnet_rows(subnets: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Optional enriched rows for name hints; empty list is fine — resolve uses TMC cache."""
    rows = subnets if isinstance(subnets, list) else []
    if not rows:
        return []
    try:
        from internal.subnet_names import enrich_subnet_rows

        return enrich_subnet_rows(rows)
    except Exception:
        return rows


def build_pump_alerts_desk(subnets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Fast pump desk payload — file-backed ladder, no background kicks on GET."""
    rows = _pump_subnet_rows(subnets)
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
            "desk": True,
        }

    early, pumping, cooling = _collect_pump_buckets(state, rows, desk=True)
    alerts = (
        _sort_bucket(early, _MAX_EARLY, row_builder=build_desk_row)
        + _sort_bucket(pumping, _MAX_PUMPING, row_builder=build_desk_row)
        + _sort_bucket(cooling, _MAX_COOLING, row_builder=build_desk_row)
    )
    payload = _finalize_pump_payload(alerts, desk=True)
    payload = _attach_watch_when_empty(payload, state, rows)
    try:
        from internal.pump.combined import attach_angles_to_desk

        attach_angles_to_desk(payload, state)
    except Exception:
        try:
            from internal.pump.peers import attach_peers_to_desk

            attach_peers_to_desk(payload, state)
        except Exception:
            pass
    return payload


def build_pump_alerts(subnets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Return predictive pump lane payload for SSR + GET /api/pump-alerts."""
    rows = _pump_subnet_rows(subnets)
    try:
        from internal.pump.refresh import kick_ladder_fresh, ladder_age_minutes, STALE_MINUTES
        from internal.pump.state import load_state

        # Don't block the request on a full ladder rescan — chips/UI need to stay snappy.
        age = ladder_age_minutes()
        kick_ladder_fresh(force=age is None or age > float(STALE_MINUTES))
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

    early, pumping, cooling = _collect_pump_buckets(state, rows, desk=False)
    alerts = _sort_bucket(early, _MAX_EARLY) + _sort_bucket(pumping, _MAX_PUMPING) + _sort_bucket(
        cooling, _MAX_COOLING
    )

    # Background: warm whale ledger for the names on the desk (and active ladder).
    try:
        from internal.pump.taostats_overlay import active_ladder_netuids
        from internal.whales.warm import kick_whale_ledger_warm

        desk = [int(a["netuid"]) for a in alerts if a.get("netuid") is not None]
        kick_whale_ledger_warm(desk + active_ladder_netuids())
    except Exception:
        pass

    payload = _finalize_pump_payload(alerts, desk=False)
    return _attach_watch_when_empty(payload, state, rows)
