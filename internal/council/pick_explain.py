"""Explain why a subnet was or was not today's council pick (§32)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from internal.council.daily_pick import _weights_for_context
from internal.council.red_team import audit_daily_pick
from internal.council.state_vector import score_subnet_for_day
from internal.subnets.tradable import tradable_subnets, subnet_netuid

_AUDIT_GATE = 0.45


def _subnet_row(subnets: List[Dict[str, Any]], netuid: int) -> Optional[Dict[str, Any]]:
    for row in subnets:
        n = subnet_netuid(row)
        if n is not None and int(n) == int(netuid):
            return row
    return None


def explain_subnet(
    netuid: int,
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return honest gating reasons for *netuid* vs today's pick."""
    market_context = dict(market_context or {})
    market_context.setdefault("weights", _weights_for_context(market_context))
    subnets = tradable_subnets(subnets)
    row = _subnet_row(subnets, netuid)
    if row is None:
        return {"status": "not_found", "netuid": int(netuid)}

    from internal.council.daily_pick_engine import get_or_create_today_pick

    today = get_or_create_today_pick(subnets, market_context)
    pick = today.get("pick") if isinstance(today.get("pick"), dict) else {}
    cand = today.get("candidate") if isinstance(today.get("candidate"), dict) else {}
    pick_sn = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else {}
    cand_sn = cand.get("subnet") if isinstance(cand.get("subnet"), dict) else {}
    published_n = pick_sn.get("netuid")
    candidate_n = cand_sn.get("netuid")

    scored = score_subnet_for_day(row, market_context)
    audit = audit_daily_pick({**row, "confidence": scored["confidence"]}, subnets)
    final_conf = float(audit.get("adjusted_confidence") or 0.0)

    blockers: List[str] = []
    if final_conf < _AUDIT_GATE:
        blockers.append(f"Confidence {final_conf:.0%} below {_AUDIT_GATE:.0%} audit gate")
    blockers.extend(list(audit.get("concerns") or [])[:4])

    verdict = "not_today_pick"
    if published_n is not None and int(published_n) == int(netuid):
        verdict = "published"
        blockers = []
    elif candidate_n is not None and int(candidate_n) == int(netuid) and published_n is None:
        verdict = "gated_candidate"
        reason = today.get("reason")
        if reason:
            blockers.insert(0, str(reason))
    else:
        if published_n is not None:
            blockers.insert(0, f"Today's audited pick is SN{published_n}")
        elif candidate_n is not None:
            blockers.insert(0, f"Today's top candidate is SN{candidate_n}")

    score_gap = None
    if candidate_n is not None and int(candidate_n) != int(netuid):
        cand_row = _subnet_row(subnets, int(candidate_n))
        if cand_row:
            cand_score = score_subnet_for_day(cand_row, market_context)
            score_gap = round(
                float(cand_score.get("total_score") or 0) - float(scored.get("total_score") or 0),
                2,
            )
            if score_gap > 0:
                blockers.append(f"Score gap vs candidate: {score_gap:.1f} points")

    return {
        "status": "ok",
        "netuid": int(netuid),
        "name": row.get("name"),
        "verdict": verdict,
        "final_confidence": round(final_conf, 4),
        "total_score": scored.get("total_score"),
        "score_gap_vs_candidate": score_gap,
        "blockers": blockers[:6],
        "audit": audit,
        "published_netuid": published_n,
        "candidate_netuid": candidate_n,
        "date": today.get("date"),
    }
