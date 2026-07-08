"""
Hourly pick selector for the Council engine.

Scores every subnet on the 1h horizon, picks the top candidate, and runs
it through the RedTeam audit layer before returning a final payload.
"""

from typing import Any, Dict, List, Optional

from internal.council.state_vector import score_subnet_for_hour
from internal.council.red_team import audit_daily_pick

try:
    from internal.council.weights import load_weights
except Exception:
    def load_weights():
        return {"quant": 0.30, "hype": 0.25, "dark_horse": 0.20, "technical": 0.25}


def select_hourly_pick(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    market_context = dict(market_context or {})
    market_context.setdefault("weights", load_weights())

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
        hour_score = score_subnet_for_hour(sn, market_context)
        scored.append({"subnet": sn, "score": hour_score})

    scored.sort(key=lambda x: x["score"]["total_score"], reverse=True)
    top = scored[0]
    candidate = top["subnet"]
    score_payload = top["score"]

    tie_break = None
    if len(scored) >= 2:
        runner_up = scored[1]
        score_gap = top["score"]["total_score"] - runner_up["score"]["total_score"]
        if score_gap <= 2.0:
            tie_break = _apply_tie_break(top, runner_up)
            if tie_break.get("winner_changed"):
                candidate = runner_up["subnet"]
                score_payload = runner_up["score"]

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
    l_score = leader["score"]
    r_score = runner_up["score"]
    l_sn = leader["subnet"]
    r_sn = runner_up["subnet"]

    reasons: List[str] = []
    winner_changed = False

    l_conf = float(l_score.get("confidence", 0) or 0)
    r_conf = float(r_score.get("confidence", 0) or 0)
    if r_conf > l_conf + 0.02:
        reasons.append("Runner-up has higher confidence (" + str(round(r_conf, 3)) + " vs " + str(round(l_conf, 3)) + ")")
        winner_changed = True
    elif l_conf > r_conf + 0.02:
        reasons.append("Leader has higher confidence (" + str(round(l_conf, 3)) + " vs " + str(round(r_conf, 3)) + ")")

    l_contrib = l_score.get("expert_contributions", {})
    r_contrib = r_score.get("expert_contributions", {})
    l_qt = float(l_contrib.get("quant", 0)) + float(l_contrib.get("technical", 0))
    r_qt = float(r_contrib.get("quant", 0)) + float(r_contrib.get("technical", 0))
    if not winner_changed and r_qt > l_qt + 0.02:
        reasons.append("Runner-up has higher quant+technical (" + str(round(r_qt, 3)) + " vs " + str(round(l_qt, 3)) + ")")
        winner_changed = True
    elif not winner_changed and l_qt > r_qt + 0.02:
        reasons.append("Leader has higher quant+technical (" + str(round(l_qt, 3)) + " vs " + str(round(r_qt, 3)) + ")")

    if not winner_changed:
        l_vol = abs(float(l_sn.get("price_change_24h", 0) or 0))
        r_vol = abs(float(r_sn.get("price_change_24h", 0) or 0))
        if r_vol < l_vol - 0.5:
            reasons.append("Runner-up has lower 24h volatility (" + str(round(r_vol, 2)) + "% vs " + str(round(l_vol, 2)) + "%)")
            winner_changed = True
        elif l_vol < r_vol - 0.5:
            reasons.append("Leader has lower 24h volatility (" + str(round(l_vol, 2)) + "% vs " + str(round(r_vol, 2)) + "%)")

    if not winner_changed:
        l_vol_val = float(l_sn.get("volume", 0) or 0)
        r_vol_val = float(r_sn.get("volume", 0) or 0)
        if r_vol_val > l_vol_val * 1.1:
            reasons.append("Runner-up has higher volume ($" + str(int(r_vol_val)) + " vs $" + str(int(l_vol_val)) + ")")
            winner_changed = True

    if not reasons:
        reasons.append("Scores within 2.0 but no tie-break rule triggered; leader retained.")

    return {
        "winner_changed": winner_changed,
        "reasons": reasons,
        "leader": {"netuid": l_sn.get("netuid"), "name": l_sn.get("name")},
        "runner_up": {"netuid": r_sn.get("netuid"), "name": r_sn.get("name")},
    }
