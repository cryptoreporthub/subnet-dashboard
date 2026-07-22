"""K3-7 hero brief — trader-facing move / thesis / vs / trigger for the dossier."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_AUDIT_GATE_PCT = 45

_BANNED_IN_HERO = (
    "council scan",
    "blocked:",
    "audit gate",
    "size in",
    "wait —",
    "publish",
    "leads 24h",
)


def _pct(raw: Any) -> int:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return 0
    if 0.0 <= val <= 1.0:
        val *= 100.0
    return max(0, min(100, int(round(val))))


def _pick_block(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pick = payload.get("pick")
    if isinstance(pick, dict) and pick.get("subnet"):
        return pick
    cand = payload.get("candidate")
    if isinstance(cand, dict) and cand.get("subnet"):
        return cand
    return None


def _subnet_label(block: Optional[Dict[str, Any]]) -> str:
    """LONG line label — prefer human name + netuid when distinct."""
    if not isinstance(block, dict):
        return "no long"
    sn = block.get("subnet") if isinstance(block.get("subnet"), dict) else {}
    name = str(sn.get("name") or "").strip()
    netuid = sn.get("netuid")
    if name and not re.match(r"^SN\d+$", name, re.I):
        if netuid is not None:
            return f"{name} (SN{netuid})"
        return name
    if netuid is not None:
        return f"SN{netuid}"
    return "this subnet"


def _short_name(block: Optional[Dict[str, Any]]) -> str:
    if not isinstance(block, dict):
        return "no long"
    sn = block.get("subnet") if isinstance(block.get("subnet"), dict) else {}
    name = sn.get("name")
    netuid = sn.get("netuid")
    if name:
        return str(name)
    if netuid is not None:
        return f"SN{netuid}"
    return "no long"


def _concerns(block: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(block, dict):
        return []
    audit = block.get("audit") if isinstance(block.get("audit"), dict) else {}
    raw = audit.get("concerns") or []
    return [str(c).strip() for c in raw if c]


def _humanize_concern(text: str) -> str:
    t = text.strip()
    low = t.lower()
    if "overvalued" in low:
        return "valuation drag"
    if "thin volume" in low or "volume too thin" in low:
        return "volume too thin to size"
    if "low liquidity" in low or "liquidity" in low:
        return "liquidity too thin"
    if "volatility" in low:
        return "volatility still elevated"
    if "risk flag" in low:
        return "risk flags quiet" if "quiet" in low else "risk flags on chain"
    if len(t) > 56:
        return t[:53] + "…"
    return t


def _axis_from_role(role: str) -> str:
    low = (role or "").lower()
    if "momentum" in low or "pulse" in low:
        return "momentum"
    if "liquid" in low:
        return "liquidity"
    if "volume" in low or "thin" in low:
        return "volume"
    if "valuat" in low or "rich" in low or "price" in low:
        return "valuation"
    if "emission" in low or "yield" in low:
        return "emission"
    if "social" in low or "buzz" in low:
        return "social buzz"
    return "signals"


def _vs_line(
    payload: Dict[str, Any],
    shortlist: List[Dict[str, Any]],
    *,
    audit_pick: bool,
) -> str:
    if not shortlist:
        if str(payload.get("action") or "").upper() == "HOLD" and not audit_pick:
            return ""
        return ""

    if audit_pick:
        alt = shortlist[0] if isinstance(shortlist[0], dict) else {}
        name = alt.get("name") or (
            f"SN{alt.get('netuid')}" if alt.get("netuid") is not None else "runner-up"
        )
        why = (alt.get("role") or alt.get("why_not") or "thinner book").strip()
        return f"Passed {name} — {why}. We sized the one we can actually exit."

    if len(shortlist) >= 2:
        a, b = shortlist[0], shortlist[1]
        if isinstance(a, dict) and isinstance(b, dict):
            an = a.get("name") or f"SN{a.get('netuid')}"
            bn = b.get("name") or f"SN{b.get('netuid')}"
            ax_a = _axis_from_role(str(a.get("role") or ""))
            ax_b = _axis_from_role(str(b.get("role") or ""))
            return (
                f"Beat {an} on {ax_a}; lost to {bn} on {ax_b}. "
                "Neither cleared the bar either."
            )

    alt = shortlist[0] if isinstance(shortlist[0], dict) else {}
    name = alt.get("name") or (f"SN{alt.get('netuid')}" if alt.get("netuid") is not None else "runner-up")
    why = (alt.get("role") or alt.get("why_not") or "").strip()
    if why:
        return f"Also weighed {name} — {why}."
    return f"Also weighed {name}."


def _trigger_line(conviction: int, blockers: List[str], *, audit_pick: bool) -> str:
    if audit_pick or conviction >= _AUDIT_GATE_PCT:
        return ""
    blocker = ""
    for raw in blockers:
        b = _humanize_concern(raw)
        if b and "quiet" not in b:
            blocker = b
            break
    if "valuation" in blocker:
        blocker = "valuation drag clears"
    elif "volume" in blocker or "liquidity" in blocker:
        blocker = "volume supports size"
    elif blocker:
        blocker = f"{blocker} clears"
    if blocker:
        return f"Flip to LONG when conviction ≥ {_AUDIT_GATE_PCT}% and {blocker}."
    gap = max(0, _AUDIT_GATE_PCT - conviction)
    return f"Flip to LONG when conviction ≥ {_AUDIT_GATE_PCT}% (+{gap} pts)."


def _evidence_drivers(
    block: Optional[Dict[str, Any]],
    payload: Dict[str, Any],
) -> List[Dict[str, str]]:
    """Up to three tagged drivers for S1 hero evidence."""
    out: List[Dict[str, str]] = []
    signals = []
    if isinstance(block, dict):
        signals.extend(block.get("active_signals") or [])
        impact = block.get("signal_impact") if isinstance(block.get("signal_impact"), dict) else {}
        for key in ("flow", "momentum", "social"):
            if impact.get(key) is not None:
                signals.append(f"{key}:{impact.get(key)}")
    for raw in signals:
        text = str(raw).strip()
        if not text:
            continue
        low = text.lower()
        if "social" in low or "buzz" in low or "hype" in low:
            tag = "social"
        elif "flow" in low or "volume" in low or "liquid" in low:
            tag = "flow"
        else:
            tag = "tech"
        out.append({"tag": tag, "label": text[:48]})
        if len(out) >= 3:
            break
    if len(out) < 3 and isinstance(payload.get("shortlist"), list):
        for alt in payload["shortlist"][:2]:
            if not isinstance(alt, dict):
                continue
            role = str(alt.get("role") or alt.get("why_not") or "").strip()
            if not role:
                continue
            out.append({"tag": _axis_from_role(role), "label": role[:48]})
            if len(out) >= 3:
                break
    return out[:3]


def _tao_bench_7d(payload: Dict[str, Any]) -> Optional[float]:
    """Average 7d price change across shortlist as hold-TAO proxy."""
    vals: List[float] = []
    for row in payload.get("shortlist") or []:
        if not isinstance(row, dict):
            continue
        for key in ("price_change_7d", "change_7d"):
            if row.get(key) is not None:
                try:
                    vals.append(float(row[key]))
                    break
                except (TypeError, ValueError):
                    pass
    if not vals:
        ctx = payload.get("market_context") if isinstance(payload.get("market_context"), dict) else {}
        if ctx.get("tao_change_7d") is not None:
            try:
                return float(ctx["tao_change_7d"])
            except (TypeError, ValueError):
                pass
        if ctx.get("tao_change_24h") is not None:
            try:
                return float(ctx["tao_change_24h"])
            except (TypeError, ValueError):
                pass
        return None
    return sum(vals) / len(vals)


def _vs_hold_tao_line(block: Optional[Dict[str, Any]], payload: Dict[str, Any]) -> str:
    if not isinstance(block, dict):
        return ""
    sn = block.get("subnet") if isinstance(block.get("subnet"), dict) else {}
    pick_chg = None
    for key in ("price_change_7d", "change_7d"):
        if sn.get(key) is not None:
            try:
                pick_chg = float(sn[key])
                break
            except (TypeError, ValueError):
                pass
    bench = _tao_bench_7d(payload)
    if pick_chg is None or bench is None:
        return ""
    excess = pick_chg - bench
    return (
        f"vs hold TAO 7d: pick {pick_chg:+.1f}% · bench {bench:+.1f}% · "
        f"{excess:+.1f}% vs network"
    )


def build_dpick_brief(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return move / thesis / vs / trigger for council_stage hero."""
    empty: Dict[str, Any] = {
        "move": "",
        "thesis": "",
        "vs": "",
        "vs_hold_tao": "",
        "evidence_drivers": [],
        "trigger": "",
        "tone": "neutral",
        "blockers": [],
    }
    if not isinstance(payload, dict):
        return empty

    act = str(payload.get("action") or "HOLD").upper()
    audit_pick = isinstance(payload.get("pick"), dict) and payload["pick"].get("subnet")
    cand = isinstance(payload.get("candidate"), dict) and payload["candidate"].get("subnet")
    block = payload.get("pick") if audit_pick else payload.get("candidate")
    conviction = _pct(
        (block or {}).get("final_confidence", (block or {}).get("confidence", 0))
        if block
        else 0
    )
    concerns = [_humanize_concern(c) for c in _concerns(block if isinstance(block, dict) else None)]
    shortlist = payload.get("shortlist") if isinstance(payload.get("shortlist"), list) else []
    vs = _vs_line(payload, shortlist, audit_pick=bool(audit_pick))

    if audit_pick:
        label = _subnet_label(block if isinstance(block, dict) else None)
        move = f"LONG · {label}"
        thesis = (
            "Judges aligned on 24h mean-reversion with room left in the move. "
            "Liquidity can take size; risk flags are quiet."
        )
        trigger = ""
        tone = "go"
    elif cand and act == "HOLD":
        label = _short_name(block if isinstance(block, dict) else None)
        move = f"HOLD · {label}"
        thesis = (
            "Closest long on the 24h desk — but conviction is still short of a sized long. "
            "Price looks rich vs peers; no sized long until that gap closes."
        )
        trigger = _trigger_line(conviction, concerns, audit_pick=False)
        tone = "hold"
    elif act == "HOLD":
        move = "HOLD · no long"
        thesis = (
            "Nothing on the shortlist clears conviction and risk together. "
            "Sitting out is the call."
        )
        if shortlist:
            vs = (
                vs
                or f"{len(shortlist)} names reviewed — all failed liquidity or valuation. "
                "Details in Deliberation."
            )
        trigger = ""
        tone = "neutral"
    elif act in ("LONG", "BUY"):
        label = _subnet_label(block if isinstance(block, dict) else None)
        move = f"LONG · {label}"
        thesis = (
            "Judges aligned on 24h setup with room left in the move. "
            "Liquidity can take size; risk flags are quiet."
        )
        trigger = ""
        tone = "go"
    elif act in ("SHORT", "SELL"):
        label = _subnet_label(block if isinstance(block, dict) else None)
        move = f"REDUCE · {label}"
        thesis = "Council lean is defensive on this name for the 24h window."
        trigger = ""
        tone = "caution"
    else:
        label = _short_name(block if isinstance(block, dict) else None)
        move = f"HOLD · {label}"
        thesis = "Council is tracking this name — no sized call yet."
        trigger = _trigger_line(conviction, concerns, audit_pick=False)
        tone = "neutral"

    return {
        "move": move,
        "thesis": thesis,
        "vs": vs,
        "vs_hold_tao": _vs_hold_tao_line(block if isinstance(block, dict) else None, payload),
        "evidence_drivers": _evidence_drivers(block if isinstance(block, dict) else None, payload),
        "trigger": trigger,
        "tone": tone,
        "blockers": concerns[:3],
    }


def attach_brief_to_daily_pick(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    base = dict(payload) if isinstance(payload, dict) else {}
    base["brief"] = build_dpick_brief(base)
    return base


def hero_copy_is_clean(brief: Dict[str, Any]) -> bool:
    """True when move/thesis avoid audit-log banned phrases."""
    blob = f"{brief.get('move', '')} {brief.get('thesis', '')}".lower()
    return not any(b in blob for b in _BANNED_IN_HERO)
