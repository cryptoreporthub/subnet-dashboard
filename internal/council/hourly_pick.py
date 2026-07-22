"""
Hourly pick selector for the Council engine.

Scores every subnet on the 1h horizon, picks the top candidate, and runs
it through the RedTeam audit layer before returning a final payload.
"""

import copy
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.state_vector import (
    attach_council_prediction,
    pick_reasons,
    score_subnet_for_hour,
    unpack_score_learning_fields,
)
from internal.council.red_team import audit_daily_pick
from internal.subnets.tradable import tradable_subnets

try:
    from internal.council.weights import effective_weights
except Exception:
    def effective_weights(market_data=None, path=None):
        return {"quant": 0.30, "hype": 0.25, "dark_horse": 0.20, "technical": 0.25}


_PICK_CACHE: Dict[str, Any] = {"key": None, "ts": 0.0, "payload": None}
_PICK_CACHE_TTL = int(os.environ.get("HOURLY_PICK_CACHE_TTL", "60"))


def clear_hourly_pick_cache() -> None:
    """Test helper — drop cached hourly pick."""
    _PICK_CACHE.update(key=None, ts=0.0, payload=None)


def _weights_for_context(market_context: Dict[str, Any]) -> Dict[str, float]:
    return effective_weights({
        "avg_change_24h": market_context.get("tao_change_24h", 0),
        "breadth": market_context.get("breadth", "neutral"),
        "volatility": market_context.get("volatility", 0),
        "gainers": market_context.get("gainers", 0),
        "losers": market_context.get("losers", 0),
    })


def select_hourly_pick(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    market_context = dict(market_context or {})
    market_context.setdefault("weights", _weights_for_context(market_context))
    subnets = tradable_subnets(subnets)

    from internal.council.score_cache import universe_cache_key

    cache_key = universe_cache_key(subnets, market_context)
    now = time.time()
    if (
        _PICK_CACHE["key"] == cache_key
        and now - float(_PICK_CACHE["ts"]) < _PICK_CACHE_TTL
        and isinstance(_PICK_CACHE.get("payload"), dict)
    ):
        return copy.deepcopy(_PICK_CACHE["payload"])

    if not subnets:
        empty = {
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
            "signal_impact": None,
            "signal_contributions": None,
            "active_signals": [],
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        _PICK_CACHE.update(key=cache_key, ts=now, payload=copy.deepcopy(empty))
        return empty

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
    final_confidence = audit["adjusted_confidence"]
    learning = unpack_score_learning_fields(score_payload)
    prediction = attach_council_prediction(
        candidate, score_payload, final_confidence, horizon_type="hour", horizon_hours=1
    )
    try:
        from internal.subnets.impact import impact_profile

        impact = impact_profile(candidate)
    except Exception:
        impact = None
    reasons = pick_reasons(candidate, learning["signal_impact"])

    result = {
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
        "impact": impact,
        "reasons": reasons,
        "prediction": prediction,
        "signal_impact": learning["signal_impact"],
        "signal_contributions": learning["signal_contributions"],
        "active_signals": learning["active_signals"],
        "generated_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _PICK_CACHE.update(key=cache_key, ts=now, payload=copy.deepcopy(result))
    return result


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

    if not reasons:
        reasons.append("Scores within 2.0 but no tie-break rule triggered; leader retained.")

    return {
        "winner_changed": winner_changed,
        "reasons": reasons,
        "leader": {"netuid": l_sn.get("netuid"), "name": l_sn.get("name")},
        "runner_up": {"netuid": r_sn.get("netuid"), "name": r_sn.get("name")},
    }
