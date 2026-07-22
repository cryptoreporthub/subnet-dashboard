"""K3-2b — council deliberation shortlist for dpick / mindmap summary."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.state_vector import score_subnet_for_day
from internal.subnet_names import name_for_netuid
from internal.subnets.tradable import tradable_subnets

logger = logging.getLogger(__name__)

_EXPERT_LABELS = {"quant": "Oracle", "hype": "Echo", "dark_horse": "Pulse", "technical": "Pulse"}


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _pick_block(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    for key in ("pick", "candidate"):
        block = payload.get(key)
        if isinstance(block, dict) and block.get("subnet"):
            return block
    return None


def _picked_netuid(payload: Optional[Dict[str, Any]]) -> Optional[int]:
    block = _pick_block(payload)
    if not block:
        return None
    sn = block.get("subnet") if isinstance(block.get("subnet"), dict) else block
    nu = sn.get("netuid") if isinstance(sn, dict) else None
    if nu is None:
        return None
    try:
        return int(nu)
    except (TypeError, ValueError):
        return None


def _conviction_pct(raw: Any) -> int:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return 0
    if 0.0 <= val <= 1.0:
        val *= 100.0
    return max(0, min(100, int(round(val))))


def _why_not(pick_block: Dict[str, Any], runner_score: Dict[str, Any], rank: int) -> Optional[str]:
    audit = pick_block.get("audit") if isinstance(pick_block.get("audit"), dict) else {}
    concerns = audit.get("concerns") or []
    if concerns and rank == 2:
        return str(concerns[0])[:120]
    reasons = runner_score.get("reasons") or []
    if isinstance(reasons, list) and reasons:
        return str(reasons[0])[:120]
    return None


def _dissenters(pick_block: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(pick_block, dict):
        return []
    contrib = pick_block.get("expert_contributions")
    if not isinstance(contrib, dict):
        return []
    numeric = {
        k: float(v)
        for k, v in contrib.items()
        if k in _EXPERT_LABELS and isinstance(v, (int, float))
    }
    if len(numeric) < 2:
        return []
    audit = pick_block.get("audit") if isinstance(pick_block.get("audit"), dict) else {}
    if not audit.get("concerns"):
        return []
    weakest = min(numeric, key=numeric.get)
    return [_EXPERT_LABELS.get(weakest, str(weakest).title())]


def build_deliberation_shortlist(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
    daily_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return V2 §4A deliberation payload; alternatives may be empty when data is thin."""
    market_context = dict(market_context or {})
    subnets = tradable_subnets(subnets)
    empty: Dict[str, Any] = {
        "picked": None,
        "alternatives": [],
        "total_considered": 0,
        "council_unanimous": True,
        "dissenters": [],
        "last_updated": _utcnow_z(),
    }
    if not subnets:
        return empty

    scored: List[Dict[str, Any]] = []
    for sn in subnets:
        try:
            score = score_subnet_for_day(sn, market_context)
            scored.append({"subnet": sn, "score": score})
        except Exception:
            continue
    scored.sort(key=lambda row: float(row["score"].get("total_score", 0)), reverse=True)
    if not scored:
        return empty

    pick_block = _pick_block(daily_payload)
    picked_nu = _picked_netuid(daily_payload)
    if picked_nu is None:
        top = scored[0]
        picked_nu = top["subnet"].get("netuid")
        pick_block = {
            "subnet": {
                "netuid": top["subnet"].get("netuid"),
                "name": top["subnet"].get("name"),
            },
            "final_confidence": top["score"].get("confidence", 0),
            "confidence": top["score"].get("confidence", 0),
            "expert_contributions": top["score"].get("expert_contributions", {}),
            "audit": {"concerns": []},
        }

    pick_sn: Dict[str, Any] = {}
    pick_conv = 0
    if isinstance(pick_block, dict):
        pick_sn = pick_block.get("subnet") if isinstance(pick_block.get("subnet"), dict) else {}
        pick_conv = _conviction_pct(
            pick_block.get("final_confidence", pick_block.get("confidence", 0))
        )

    alternatives: List[Dict[str, Any]] = []
    rank = 2
    for row in scored:
        sn = row["subnet"]
        nu = sn.get("netuid")
        try:
            if nu is not None and picked_nu is not None and int(nu) == int(picked_nu):
                continue
        except (TypeError, ValueError):
            pass
        conv = _conviction_pct(
            row["score"].get("confidence", row["score"].get("total_score", 0))
        )
        ec = row["score"].get("expert_contributions") or {}
        # Strip nested metadata — peel only needs the four expert scores
        expert_scores = {
            k: ec.get(k)
            for k in ("quant", "hype", "dark_horse", "technical")
            if ec.get(k) is not None
        }
        alternatives.append(
            {
                "netuid": nu,
                "name": name_for_netuid(nu) if nu is not None else "SN?",
                "conviction": conv,
                "why_not": _why_not(pick_block or {}, row["score"], rank),
                "expert_contributions": expert_scores,
                "rank": rank,
                "price_change_24h": sn.get("price_change_24h"),
                "emission": sn.get("emission"),
                "volume": sn.get("volume"),
            }
        )
        rank += 1
        if len(alternatives) >= 8:
            break

    gate = 45 if pick_conv < 45 else pick_conv
    alternatives.sort(key=lambda a: abs(int(a.get("conviction") or 0) - gate))

    dissenters = _dissenters(pick_block)
    picked = None
    if picked_nu is not None:
        picked = {
            "netuid": pick_sn.get("netuid", picked_nu),
            "name": name_for_netuid(picked_nu),
            "conviction": pick_conv,
        }
    return {
        "picked": picked,
        "alternatives": alternatives,
        "total_considered": len(scored),
        "council_unanimous": len(dissenters) == 0,
        "dissenters": dissenters,
        "last_updated": _utcnow_z(),
    }


def shortlist_cards_for_template(deliberation: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Map §4A alternatives to council_stage card rows (dpick.shortlist)."""
    cards: List[Dict[str, Any]] = []
    for alt in deliberation.get("alternatives") or []:
        if not isinstance(alt, dict):
            continue
        cards.append(
            {
                "netuid": alt.get("netuid"),
                "name": alt.get("name"),
                "conviction": alt.get("conviction"),
                "role": alt.get("why_not"),
                "stance": "LONG",
                "price_change_24h": alt.get("price_change_24h"),
                "emission": alt.get("emission"),
                "volume": alt.get("volume"),
            }
        )
    return cards


def attach_shortlist_to_daily_pick(
    daily_payload: Optional[Dict[str, Any]],
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Enrich daily_pick_stage dict with template-ready shortlist list."""
    base = dict(daily_payload) if isinstance(daily_payload, dict) else {}
    try:
        deliberation = build_deliberation_shortlist(subnets, market_context, base)
        cards = shortlist_cards_for_template(deliberation)
        base["shortlist"] = cards if len(cards) >= 2 else []
    except Exception as exc:
        logger.warning("dpick.shortlist attach failed: %s", exc)
        base["shortlist"] = []
    return base
