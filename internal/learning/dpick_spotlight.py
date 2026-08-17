"""Hero / weighing alignment for HOLD days — spotlight judge-long desk lead."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from internal.council.publish_gate import directional_publish_guard


def _judge_row_as_candidate(row: Dict[str, Any]) -> Dict[str, Any]:
    conv = int(row.get("conviction") or 0)
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
    out: Dict[str, Any] = {
        "subnet": {
            "netuid": row.get("netuid"),
            "name": row.get("name"),
        },
        "final_confidence": fc,
        "confidence": fc,
        "spotlight_source": "judge_long",
    }
    if scores_at_creation:
        out["judge_scores_at_creation"] = scores_at_creation
    return out


def attach_hero_spotlight_candidate(
    payload: Dict[str, Any],
    subnets: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """When HOLD blocks a bearish expert tail, spotlight the top judge-long name."""
    if not isinstance(payload, dict) or payload.get("pick"):
        return payload
    if str(payload.get("action", "HOLD")).upper() != "HOLD":
        return payload
    expert = payload.get("candidate")
    if not isinstance(expert, dict):
        return payload
    if directional_publish_guard(expert).get("approved"):
        return payload

    from internal.simivision.weighing_room import _judge_long_rows

    rows = _judge_long_rows(list(subnets or []), limit=1)
    if not rows:
        return payload
    top = rows[0]
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
    out["candidate"] = _judge_row_as_candidate(top)
    out["hero_spotlight_source"] = "judge_long"
    return out
