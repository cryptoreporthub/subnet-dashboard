"""
Daily pick selector for the Council engine.

Scores every subnet on the 24h horizon, picks the top candidate, and runs
it through the RedTeam audit layer before returning a final payload.
"""

from typing import Any, Dict, List, Optional

from internal.council.state_vector import score_subnet_for_day
from internal.council.red_team import audit_daily_pick


def select_daily_pick(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Select the single audited daily pick from a list of subnets.

    Args:
        subnets: List of subnet dicts from the fetcher/API.
        market_context: Optional market-wide context (e.g. TAO change, weights).

    Returns:
        dict with subnet, score, confidence, expert_contributions,
        scenario_tags, audit, final_confidence, and action.
    """
    if not subnets:
        return {
            "subnet": None,
            "score": 0.0,
            "confidence": 0.0,
            "expert_contributions": {},
            "scenario_tags": {},
            "audit": {
                "approved": False,
                "concerns": ["No subnets provided"],
                "adjusted_confidence": 0.0,
            },
            "final_confidence": 0.0,
            "action": "long",
        }

    scored = []
    for sn in subnets:
        day_score = score_subnet_for_day(sn, market_context)
        scored.append({"subnet": sn, "score": day_score})

    scored.sort(key=lambda x: x["score"]["total_score"], reverse=True)
    top = scored[0]
    candidate = top["subnet"]
    score_payload = top["score"]

    # Enrich the candidate with scoring metadata for the RedTeam audit.
    audit_candidate = {**candidate, "confidence": score_payload["confidence"]}
    audit = audit_daily_pick(audit_candidate, subnets)

    return {
        "subnet": {
            "netuid": candidate.get("netuid"),
            "name": candidate.get("name"),
            "symbol": candidate.get("symbol"),
        },
        "score": score_payload["total_score"],
        "confidence": score_payload["confidence"],
        "expert_contributions": score_payload["expert_contributions"],
        "scenario_tags": score_payload["scenario_tags"],
        "audit": audit,
        "final_confidence": audit["adjusted_confidence"],
        "action": "long",
    }
