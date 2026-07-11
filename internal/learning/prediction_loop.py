"""Close the learning loop: pick → prediction → resolver → weights → next pick.

Bridges Council picks, ``predictions.json``, judge paper portfolios, scenario
memory, and the Soul-Map / Mindmap trail so outcomes feed the next scoring pass.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from internal.council.state_vector import build_prediction_statement
from internal.council.weights import load_weights
from internal.learning.predictions_store import append_prediction

logger = logging.getLogger(__name__)


def _dominant_expert(expert_contributions: Optional[Dict[str, Any]]) -> str:
    if not isinstance(expert_contributions, dict) or not expert_contributions:
        return "quant"
    best_name = "quant"
    best_val = float("-inf")
    for name, raw in expert_contributions.items():
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val > best_val:
            best_val = val
            best_name = str(name)
    if best_name in ("contrarian",):
        return "dark_horse"
    if best_name not in ("quant", "hype", "dark_horse", "technical"):
        return "quant"
    return best_name


def _predicted_pct_from_pick(pick: Dict[str, Any], subnet: Dict[str, Any]) -> float:
    confidence = float(pick.get("confidence", pick.get("final_confidence", 0)) or 0)
    change_24h = float(subnet.get("price_change_24h", 0) or 0)
    base = max(0.5, confidence * 5.0)
    if change_24h < -2:
        return -base
    if change_24h > 2:
        return base
    return base if pick.get("action", "long") != "short" else -base


def record_pick_prediction(
    pick: Dict[str, Any],
    subnet: Dict[str, Any],
    *,
    horizon_type: str = "hour",
    market_context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Persist a Council pick as a pending prediction and open judge positions.

    Returns the stored prediction dict, or None when skipped (duplicate / invalid).
    """
    if not isinstance(pick, dict) or not isinstance(subnet, dict):
        return None

    netuid = subnet.get("netuid")
    if netuid is None:
        subnet_info = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else {}
        netuid = subnet_info.get("netuid")
    if netuid is None:
        return None

    ref_price = float(subnet.get("price", 0) or 0)
    if ref_price <= 0:
        return None

    expert_contributions = pick.get("expert_contributions") or {}
    expert = _dominant_expert(expert_contributions)
    predicted_pct = _predicted_pct_from_pick(pick, subnet)
    horizon_hours = 1 if horizon_type == "hour" else 4
    now = datetime.now(timezone.utc)

    prediction = build_prediction_statement(
        sn=subnet,
        predicted_pct=predicted_pct,
        horizon=horizon_hours,
        ref_price=ref_price,
        signal_source=f"council_{horizon_type}_pick",
        expert=expert,
        now=now.replace(tzinfo=None),
        signal_contributions=expert_contributions if expert_contributions else None,
        horizon_type=horizon_type,
    )
    prediction["pick_source"] = "council"
    prediction["pick_score"] = pick.get("score")
    prediction["pick_confidence"] = pick.get("confidence", pick.get("final_confidence"))

    scenario_id = _link_scenario_memory(prediction, subnet, market_context)
    if scenario_id:
        prediction["scenario_id"] = scenario_id

    if not append_prediction(prediction):
        return None

    expert_weights = load_weights()
    try:
        from internal.judges.tracker import on_prediction_created

        judge_scores = on_prediction_created(
            prediction,
            signal_impact=pick.get("signals"),
            subnet=subnet,
            expert_weights=expert_weights,
        )
        prediction["judge_scores_at_creation"] = judge_scores
    except Exception as exc:
        logger.warning("Judge on_prediction_created failed: %s", exc)

    _append_mindmap_trail(pick, prediction, horizon_type)
    _mirror_pick_to_soul_map(pick, prediction, horizon_type)

    try:
        from internal.learning.trail_bus import emit_conviction_update, emit_signal_triggered

        conf = pick.get("confidence", pick.get("final_confidence"))
        emit_conviction_update(
            subnet=prediction.get("name"),
            netuid=prediction.get("netuid"),
            conviction=float(conf) * 100 if conf and float(conf) <= 1 else conf,
            horizon_type=horizon_type,
            evidence={"pick_score": pick.get("score"), "expert": expert},
        )
        emit_signal_triggered(
            subnet=prediction.get("name"),
            netuid=prediction.get("netuid"),
            signal_name=f"council_{horizon_type}_pick",
            direction=prediction.get("direction"),
            evidence={"prediction_id": prediction.get("id")},
        )
    except Exception as exc:
        logger.warning("Pick trail emission failed: %s", exc)

    return prediction


def _link_scenario_memory(
    prediction: Dict[str, Any],
    subnet: Dict[str, Any],
    market_context: Optional[Dict[str, Any]],
) -> Optional[str]:
    try:
        from internal.council import scenario_memory
        from internal.council.state_vector import _scenario_tags, _compute_technical_indicators

        indicators = _compute_technical_indicators(subnet)
        tags = _scenario_tags(subnet, indicators, market_context or {})
        created = scenario_memory.add_scenario(
            name=str(prediction.get("name") or subnet.get("name") or f"SN{prediction.get('netuid')}"),
            features={
                **tags,
                "netuid": prediction.get("netuid"),
                "direction": prediction.get("direction"),
                "predicted_pct": prediction.get("predicted_pct"),
                "horizon_type": prediction.get("horizon_type"),
                "expert": prediction.get("expert"),
            },
            outcome=None,
        )
        try:
            from internal.learning.trail_bus import emit_scenario_tagged

            emit_scenario_tagged(created)
        except Exception:
            pass
        return created.get("id")
    except Exception as exc:
        logger.warning("Scenario memory link failed: %s", exc)
        return None


def _append_mindmap_trail(
    pick: Dict[str, Any],
    prediction: Dict[str, Any],
    horizon_type: str,
) -> None:
    try:
        from internal.council.mindmap_bridge import MindmapBridge

        bridge = MindmapBridge()
        bridge.append_learning_trail(
            {
                "time": prediction.get("created_at"),
                "subnet": prediction.get("name"),
                "netuid": prediction.get("netuid"),
                "evidence": pick.get("scenario_tags") or pick.get("signals") or {},
                "signal": prediction.get("signal_source"),
                "decision": pick.get("action", "long"),
                "prediction": prediction.get("statement"),
                "judge": prediction.get("expert"),
                "horizon_type": horizon_type,
                "prediction_id": prediction.get("id"),
            }
        )
    except Exception as exc:
        logger.warning("Mindmap trail append failed: %s", exc)


def _mirror_pick_to_soul_map(
    pick: Dict[str, Any],
    prediction: Dict[str, Any],
    horizon_type: str,
) -> None:
    """Keep soul_map_state.last_pick in sync for dashboard / rotation readers."""
    try:
        from internal.council.weights import _load_raw, _save_raw

        data = _load_raw()
        sms = data.setdefault("soul_map_state", {})
        if not isinstance(sms, dict):
            sms = {}
            data["soul_map_state"] = sms
        sms.setdefault("learning_trail", [])
        if isinstance(sms["learning_trail"], list):
            sms["learning_trail"].append(
                {
                    "prediction_id": prediction.get("id"),
                    "netuid": prediction.get("netuid"),
                    "name": prediction.get("name"),
                    "horizon_type": horizon_type,
                    "statement": prediction.get("statement"),
                    "expert": prediction.get("expert"),
                    "created_at": prediction.get("created_at"),
                }
            )
            sms["learning_trail"] = sms["learning_trail"][-200:]
        sms[f"last_{horizon_type}_pick"] = {
            "pick": pick,
            "prediction_id": prediction.get("id"),
            "updated_at": prediction.get("created_at"),
        }
        _save_raw(data)
    except Exception as exc:
        logger.warning("Soul-map pick mirror failed: %s", exc)
