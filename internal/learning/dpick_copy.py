"""K3 copy brief — concise move / thesis / vs-alternatives for the dossier hero."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_AUDIT_GATE_PCT = 45


def _pct(raw: Any) -> int:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return 0
    if 0.0 <= val <= 1.0:
        val *= 100.0
    return max(0, min(100, int(round(val))))


def _pick_block(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ("pick", "candidate"):
        block = payload.get(key)
        if isinstance(block, dict) and block.get("subnet"):
            return block
    return None


def _subnet_name(block: Optional[Dict[str, Any]]) -> str:
    if not isinstance(block, dict):
        return "this subnet"
    sn = block.get("subnet") if isinstance(block.get("subnet"), dict) else {}
    nu = sn.get("netuid")
    name = sn.get("name")
    if name:
        return str(name)
    if nu is not None:
        return f"SN{nu}"
    return "this subnet"


def _first_reason(block: Optional[Dict[str, Any]], payload: Dict[str, Any]) -> Optional[str]:
    if isinstance(block, dict):
        reasons = block.get("reasons")
        if isinstance(reasons, list) and reasons:
            return str(reasons[0]).strip()
    reason = payload.get("reason")
    return str(reason).strip() if reason else None


def _concerns(block: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(block, dict):
        return []
    audit = block.get("audit") if isinstance(block.get("audit"), dict) else {}
    raw = audit.get("concerns") or []
    return [str(c).strip() for c in raw if c]


def _humanize_concern(text: str) -> str:
    t = text.strip()
    low = t.lower()
    if "audit gate" in low or "below" in low and "%" in t:
        return "Below 45% confidence floor"
    if low.startswith("thin volume"):
        return "Volume too thin to size"
    if low.startswith("low liquidity"):
        return "Liquidity too low"
    if "overvalued" in low:
        return "Overvalued vs peers"
    if "volatility" in low:
        m = re.search(r"([+-]?\d+\.?\d*)%", t)
        return f"Volatility risk ({m.group(1)}%)" if m else "Volatility risk"
    if low.startswith("risk flags"):
        return "Risk flags on chain"
    if low.startswith("missing critical"):
        return "Missing market data"
    if len(t) > 72:
        return t[:69] + "…"
    return t


def _horizon_label(payload: Dict[str, Any]) -> str:
    h = payload.get("time_horizon") or payload.get("horizon") or "24h"
    return str(h).strip() or "24h"


def _vs_alternative(shortlist: List[Dict[str, Any]]) -> Optional[str]:
    if not shortlist:
        return None
    alt = shortlist[0]
    if not isinstance(alt, dict):
        return None
    name = alt.get("name") or (f"SN{alt.get('netuid')}" if alt.get("netuid") is not None else "Runner-up")
    conv = alt.get("conviction")
    why = (alt.get("role") or alt.get("why_not") or "").strip()
    conv_bit = f" ({int(conv)}%)" if conv is not None else ""
    if why:
        return f"Passed {name}{conv_bit} — {why}"
    return f"Next in line: {name}{conv_bit}"


def build_dpick_brief(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return move / thesis / vs lines for council_stage hero."""
    empty: Dict[str, Any] = {"move": "", "thesis": "", "vs": "", "tone": "neutral", "blockers": []}
    if not isinstance(payload, dict):
        return empty

    act = str(payload.get("action") or "HOLD").upper()
    audit_pick = payload.get("pick") if isinstance(payload.get("pick"), dict) else None
    cand = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else None
    block = audit_pick or cand
    horizon = _horizon_label(payload)
    name = _subnet_name(block)
    conviction = _pct(
        (block or {}).get("final_confidence", (block or {}).get("confidence", 0))
    )
    concerns = [_humanize_concern(c) for c in _concerns(block)]
    shortlist = payload.get("shortlist") if isinstance(payload.get("shortlist"), list) else []
    vs = _vs_alternative(shortlist)
    reason = _first_reason(block, payload)

    if audit_pick:
        move = f"SIZE IN — audited {act} on {name}"
        thesis = reason or f"Top {horizon} council score with audit pass at {conviction}%"
        tone = "go"
    elif cand and act == "HOLD":
        move = f"WAIT — watch {name}, do not size in"
        blockers = concerns[:3]
        if not blockers and payload.get("reason"):
            blockers = [_humanize_concern(str(payload.get("reason")))]
        thesis_bits = [f"Leads {horizon} council scan at {conviction}% (need {_AUDIT_GATE_PCT}% to publish)"]
        if blockers:
            thesis_bits.append("Blocked: " + ", ".join(blockers[:2]))
        elif reason:
            thesis_bits.append(reason)
        thesis = ". ".join(thesis_bits)
        tone = "wait"
    elif act == "HOLD":
        move = "WAIT — no published long today"
        thesis = payload.get("reason") or "No subnet cleared confidence + risk audit"
        blockers = []
        tone = "wait"
    elif act in ("LONG", "BUY"):
        move = f"SIZE IN — {act} {name}"
        thesis = reason or f"Highest {horizon} conviction at {conviction}%"
        tone = "go"
    elif act in ("SHORT", "SELL"):
        move = f"REDUCE — {act} {name}"
        thesis = reason or f"{horizon} council lean at {conviction}%"
        tone = "caution"
    else:
        move = f"WATCH — {name}"
        thesis = reason or f"Council tracking on {horizon} lens"
        tone = "neutral"

    return {
        "move": move,
        "thesis": thesis,
        "vs": vs or "",
        "tone": tone,
        "blockers": concerns[:3],
    }


def attach_brief_to_daily_pick(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    base = dict(payload) if isinstance(payload, dict) else {}
    base["brief"] = build_dpick_brief(base)
    return base
