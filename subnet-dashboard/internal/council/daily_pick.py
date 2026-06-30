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

    # Tie-break: if the runner-up is within 2.0 points, apply deterministic rules.
    tie_break = None
    if len(scored) >= 2:
        runner_up = scored[1]
        score_gap = top["score"]["total_score"] - runner_up["score"]["total_score"]
        if score_gap <= 2.0:
            tie_break = _apply_tie_break(top, runner_up)
            if tie_break.get("winner_changed"):
                candidate = runner_up["subnet"]
                score_payload = runner_up["score"]

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
        "tie_break": tie_break,
    }


def _apply_tie_break(
    leader: Dict[str, Any], runner_up: Dict[str, Any]
) -> Dict[str, Any]:
    """Resolve a near-tie between two daily-pick candidates.

    Rules (in order):
      1. Higher confidence wins.
      2. Higher combined quant + technical contribution wins (day lens favours evidence/trend).
      3. Lower 24h volatility (|price_change_24h|) wins.
      4. Higher volume wins.
    """
    l_score = leader["score"]
    r_score = runner_up["score"]
    l_sn = leader["subnet"]
    r_sn = runner_up["subnet"]

    reasons: List[str] = []
    winner_changed = False

    l_conf = float(l_score.get("confidence", 0) or 0)
    r_conf = float(r_score.get("confidence", 0) or 0)
    if r_conf > l_conf + 0.02:
        reasons.append(f"Runner-up has higher confidence ({r_conf:.3f} vs {l_conf:.3f})")
        winner_changed = True
    elif l_conf > r_conf + 0.02:
        reasons.append(f"Leader has higher confidence ({l_conf:.3f} vs {r_conf:.3f})")

    l_contrib = l_score.get("expert_contributions") or {}
    r_contrib = r_score.get("expert_contributions") or {}
    l_evidence = float(l_contrib.get("quant", 0)) + float(l_contrib.get("technical", 0))
    r_evidence = float(r_contrib.get("quant", 0)) + float(r_contrib.get("technical", 0))
    if not winner_changed and r_evidence > l_evidence + 0.02:
        reasons.append(f"Runner-up has stronger evidence score ({r_evidence:.3f} vs {l_evidence:.3f})")
        winner_changed = True
    elif l_evidence > r_evidence + 0.02:
        reasons.append(f"Leader has stronger evidence score ({l_evidence:.3f} vs {r_evidence:.3f})")

    l_vol = abs(float(l_sn.get("price_change_24h", 0) or 0))
    r_vol = abs(float(r_sn.get("price_change_24h", 0) or 0))
    if not winner_changed and r_vol < l_vol - 0.5:
        reasons.append(f"Runner-up is less volatile ({r_vol:.2f}% vs {l_vol:.2f}%)")
        winner_changed = True
    elif l_vol < r_vol - 0.5:
        reasons.append(f"Leader is less volatile ({l_vol:.2f}% vs {r_vol:.2f}%)")

    l_liq = float(l_sn.get("volume", 0) or 0)
    r_liq = float(r_sn.get("volume", 0) or 0)
    if not winner_changed and r_liq > l_liq * 1.1:
        reasons.append(f"Runner-up has higher volume ({r_liq:,.0f} vs {l_liq:,.0f})")
        winner_changed = True
    elif l_liq > r_liq * 1.1:
        reasons.append(f"Leader has higher volume ({l_liq:,.0f} vs {r_liq:,.0f})")

    if not reasons:
        reasons.append("No decisive tie-break rule applied; leader retained by raw score.")

    return {
        "winner_changed": winner_changed,
        "leader": {"netuid": l_sn.get("netuid"), "name": l_sn.get("name"), "score": l_score.get("total_score")},
        "runner_up": {"netuid": r_sn.get("netuid"), "name": r_sn.get("name"), "score": r_score.get("total_score")},
        "reasons": reasons,
    }
