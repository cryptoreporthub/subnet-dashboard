"""
Daily pick selector for the Council engine.

Scores every subnet on the 24h horizon, picks the top candidate, and runs
it through the RedTeam audit layer before returning a final payload.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.state_vector import build_prediction_statement, pick_reasons, score_subnet_for_day
from internal.council.red_team import audit_daily_pick
from internal.subnets.tradable import tradable_subnets

try:
    from internal.council.weights import effective_weights
except Exception:
    def effective_weights(market_data=None, path=None):
        return {"quant": 0.30, "hype": 0.25, "dark_horse": 0.20, "technical": 0.25}


def _weights_for_context(market_context: Dict[str, Any]) -> Dict[str, float]:
    return effective_weights({
        "avg_change_24h": market_context.get("tao_change_24h", 0),
        "breadth": market_context.get("breadth", "neutral"),
        "volatility": market_context.get("volatility", 0),
        "gainers": market_context.get("gainers", 0),
        "losers": market_context.get("losers", 0),
    })


def _predicted_pct(score_payload: Dict[str, Any], sn: Dict[str, Any], pick_conf: float) -> float:
    """Prefer signal-impact move; else confidence heuristic (same as learning loop)."""
    si = score_payload.get("signal_impact") if isinstance(score_payload, dict) else None
    if isinstance(si, dict):
        raw = si.get("net_predicted_pct")
        try:
            if raw is not None and float(raw) != 0.0:
                return float(raw)
        except (TypeError, ValueError):
            pass
    base = max(0.5, float(pick_conf or 0) * 5.0)
    chg = float(sn.get("price_change_24h", 0) or 0)
    if chg < -2:
        return -base
    return base


def _attach_prediction(
    candidate: Dict[str, Any],
    score_payload: Dict[str, Any],
    final_confidence: float,
) -> Dict[str, Any]:
    """Display/learning prediction for a published or candidate pick."""
    ref = float(candidate.get("price", 0) or 0)
    predicted_pct = _predicted_pct(score_payload, candidate, final_confidence)
    contrib = score_payload.get("expert_contributions") if isinstance(score_payload, dict) else None
    return build_prediction_statement(
        sn=candidate,
        predicted_pct=predicted_pct,
        horizon=4,
        ref_price=ref,
        signal_source="council_day_pick",
        expert="quant",
        now=datetime.now(timezone.utc).replace(tzinfo=None),
        signal_contributions=contrib if isinstance(contrib, dict) else None,
        horizon_type="day",
    )


def select_daily_pick(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    market_context = dict(market_context or {})
    market_context.setdefault("weights", _weights_for_context(market_context))
    subnets = tradable_subnets(subnets)

    if not subnets:
        return {
            "subnet": None,
            "score": 0.0,
            "confidence": 0.0,
            "expert_contributions": {},
            "scenario_tags": {},
            "audit": {
                "approved": False,
                "concerns": ["No tradable subnets provided"],
                "adjusted_confidence": 0.0,
            },
            "final_confidence": 0.0,
            "action": "long",
            "prediction": None,
            "reasons": [],
        }

    scored = []
    for sn in subnets:
        day_score = score_subnet_for_day(sn, market_context)
        scored.append({"subnet": sn, "score": day_score})

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
    final_confidence = audit["adjusted_confidence"]
    prediction = _attach_prediction(candidate, score_payload, final_confidence)
    reasons = pick_reasons(candidate)
    try:
        from internal.subnets.impact import impact_profile

        impact = impact_profile(candidate)
    except Exception:
        impact = None

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
        "final_confidence": final_confidence,
        "action": "long",
        "tie_break": tie_break,
        "prediction": prediction,
        "reasons": reasons,
        "impact": impact,
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
        from internal.subnets.impact import relative_flow

        l_flow = relative_flow(l_sn)
        r_flow = relative_flow(r_sn)
        if r_flow > l_flow * 1.15 and r_flow > 0:
            reasons.append(
                "Runner-up has higher relative flow (vol/mcap "
                + str(round(r_flow, 3))
                + " vs "
                + str(round(l_flow, 3))
                + ")"
            )
            winner_changed = True
        elif l_flow > r_flow * 1.15 and l_flow > 0:
            reasons.append(
                "Leader has higher relative flow (vol/mcap "
                + str(round(l_flow, 3))
                + " vs "
                + str(round(r_flow, 3))
                + ")"
            )

    if not reasons:
        reasons.append("Scores within 2.0 but no tie-break rule triggered; leader retained.")

    return {
        "winner_changed": winner_changed,
        "reasons": reasons,
        "leader": {"netuid": l_sn.get("netuid"), "name": l_sn.get("name")},
        "runner_up": {"netuid": r_sn.get("netuid"), "name": r_sn.get("name")},
    }
