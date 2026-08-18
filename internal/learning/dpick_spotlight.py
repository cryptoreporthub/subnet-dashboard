"""Hero / weighing alignment for HOLD days — spotlight desk lead from weighing board."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from internal.council.publish_gate import directional_publish_guard


def _registry_subnets_for_spotlight(limit: int = 96) -> List[Dict[str, Any]]:
    """Registry-only subnet rows for weighing on the lite read path."""
    import json
    import os

    from internal.subnets.tradable import tradable_subnets

    path = os.path.join("config", "registry.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        rows = tradable_subnets(list(data.values()) if isinstance(data, dict) else [])
        return rows[:limit]
    except Exception:
        return []


def _hold_has_directional_conflict(payload: Dict[str, Any], expert: Dict[str, Any]) -> bool:
    """True when HOLD is due to bearish council signal, not just low confidence."""
    if not directional_publish_guard(expert).get("approved"):
        return True
    reason = str(payload.get("reason") or "").lower()
    return "directional conflict" in reason


def _weighing_row_as_candidate(row: Dict[str, Any]) -> Dict[str, Any]:
    from internal.simivision.weighing_room import conviction_pct

    conv = conviction_pct(row.get("conviction"))
    fc = conv / 100.0
    js = row.get("judge_scores") if isinstance(row.get("judge_scores"), dict) else {}
    scores_at_creation: Dict[str, Any] = {}
    for key in ("oracle", "echo", "pulse"):
        block = js.get(key)
        if not isinstance(block, dict):
            continue
        conf = block.get("confidence")
        if conf is None:
            conf = block.get("score")
        if conf is None:
            continue
        scores_at_creation[key] = {
            "confidence": float(conf),
            "score": block.get("score", conf),
        }
    source = "judge_long" if row.get("judge_long") else "weighing_lead"
    out: Dict[str, Any] = {
        "subnet": {
            "netuid": row.get("netuid"),
            "name": row.get("name"),
        },
        "final_confidence": fc,
        "confidence": fc,
        "spotlight_source": source,
    }
    if scores_at_creation:
        out["judge_scores_at_creation"] = scores_at_creation
    return out


def attach_hero_spotlight_candidate(
    payload: Dict[str, Any],
    subnets: Optional[List[Dict[str, Any]]] = None,
    *,
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """When HOLD blocks a bearish expert tail, spotlight weighing's better lead."""
    if not isinstance(payload, dict) or payload.get("pick"):
        return payload
    if str(payload.get("action", "HOLD")).upper() != "HOLD":
        return payload
    expert = payload.get("candidate")
    if not isinstance(expert, dict):
        return payload
    if not _hold_has_directional_conflict(payload, expert):
        return payload

    from internal.simivision.weighing_room import best_weighing_alternative, conviction_pct

    subnet_rows = list(subnets or []) or _registry_subnets_for_spotlight()
    expert_conv = conviction_pct(
        expert.get("final_confidence", expert.get("confidence"))
    )
    top = best_weighing_alternative(
        payload,
        subnet_rows,
        market_context=market_context,
        beat_conviction=expert_conv,
    )
    if not top:
        return payload

    expert_sn = expert.get("subnet") if isinstance(expert.get("subnet"), dict) else {}
    try:
        expert_nu = int(expert_sn.get("netuid")) if expert_sn.get("netuid") is not None else None
    except (TypeError, ValueError):
        expert_nu = None
    try:
        spotlight_nu = int(top.get("netuid")) if top.get("netuid") is not None else None
    except (TypeError, ValueError):
        spotlight_nu = None
    if expert_nu is not None and expert_nu == spotlight_nu:
        return payload

    out = dict(payload)
    out["desk_candidate"] = dict(expert)
    out["candidate"] = _weighing_row_as_candidate(top)
    out["hero_spotlight_source"] = (
        "judge_long" if top.get("judge_long") else "weighing_lead"
    )
    return out
