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
from internal.learning.predictions_store import append_prediction, has_pending_duplicate

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


def _subnet_snapshot(subnet: Dict[str, Any]) -> Dict[str, Any]:
    """Persist market context at creation for N4 backtest replay (N1 follow-up)."""
    snap = {
        k: subnet.get(k)
        for k in (
            "netuid",
            "name",
            "price_change_24h",
            "price_change_7d",
            "price_change_30d",
            "price",
            "apy",
            "emission",
            "volume",
            "social_mentions",
        )
        if subnet.get(k) is not None
    }
    try:
        from internal.analytics.market_drivers import market_driver_tags
        from internal.subnets.apy import subnet_apy_percent

        tags = market_driver_tags(subnet)
        snap.update(tags)
        apy = subnet_apy_percent(subnet)
        if apy is not None:
            snap["staking_yield_apy"] = apy
    except Exception:
        pass
    return snap


def _pump_phase_at_prediction(netuid: Any) -> Optional[str]:
    """Stamp ladder phase at pick time (pump learning step 0 — council path only)."""
    try:
        from internal.pump.state import load_state

        data = load_state()
        subnets = data.get("subnets") if isinstance(data.get("subnets"), dict) else {}
        entry = subnets.get(str(netuid)) or subnets.get(int(netuid))  # type: ignore[arg-type]
        if not isinstance(entry, dict):
            return None
        phase = entry.get("phase") or entry.get("current_phase")
        return str(phase).upper() if phase else None
    except Exception as exc:
        logger.debug("pump phase stamp skipped for SN%s: %s", netuid, exc)
        return None


def _signal_impact_from_pick(pick: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ("signal_impact", "signals"):
        raw = pick.get(key)
        if isinstance(raw, dict) and (
            raw.get("net_predicted_pct") is not None or raw.get("impacts")
        ):
            return raw
    score = pick.get("score_payload") if isinstance(pick.get("score_payload"), dict) else None
    if score and isinstance(score.get("signal_impact"), dict):
        return score["signal_impact"]
    return None


def _predicted_pct_from_pick(pick: Dict[str, Any], subnet: Dict[str, Any]) -> tuple[float, str]:
    """Signal-derived move for new predictions (§17.S2) — never confidence×5 proxy.

    Returns ``(predicted_pct, magnitude_source)``.
    """
    si = _signal_impact_from_pick(pick)
    if isinstance(si, dict):
        raw = si.get("net_predicted_pct")
        try:
            if raw is not None and float(raw) != 0.0:
                return float(raw), "signal_impact"
        except (TypeError, ValueError):
            pass
        # Build net from impacts if present
        impacts = si.get("impacts")
        if isinstance(impacts, list) and impacts:
            net = 0.0
            for item in impacts:
                if not isinstance(item, dict):
                    continue
                try:
                    mag = abs(float(item.get("magnitude_pct") or 0))
                except (TypeError, ValueError):
                    continue
                direction = str(item.get("direction") or "").lower()
                if direction in {"bullish", "up"}:
                    net += mag
                elif direction in {"bearish", "down"}:
                    net -= mag
            if net != 0.0:
                try:
                    from internal.subnets.impact import scale_move_by_impact

                    return scale_move_by_impact(net, subnet), "signal_impact"
                except Exception:
                    return round(net, 4), "signal_impact"

    # Market momentum from subnet (price change + impact scale) — still not confidence
    try:
        change_24h = float(subnet.get("price_change_24h", 0) or 0)
    except (TypeError, ValueError):
        change_24h = 0.0
    action = str(pick.get("action") or "long").lower()
    direction = str(pick.get("direction") or "").lower()
    if direction not in {"up", "down"}:
        direction = "down" if action in {"short", "sell"} else "up"

    if abs(change_24h) >= 0.5:
        mag = max(0.5, abs(change_24h) * 0.5)
    else:
        mag = 1.0  # minimal market-based floor, not confidence-scaled
    signed = mag if direction == "up" else -mag
    try:
        from internal.subnets.impact import scale_move_by_impact

        return scale_move_by_impact(signed, subnet), "market_momentum"
    except Exception:
        return round(signed, 4), "market_momentum"


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
        subnet_info = pick.get("subnet")
        if isinstance(subnet_info, dict):
            netuid = subnet_info.get("netuid")
    if netuid is None:
        return None
    try:
        from internal.subnets.tradable import is_tradable_subnet

        check = dict(subnet)
        check.setdefault("netuid", netuid)
        if not is_tradable_subnet(check):
            return None
    except Exception:
        if int(netuid) <= 0:
            return None

    if has_pending_duplicate(netuid, horizon_type):
        return None

    ref_price = float(subnet.get("price", 0) or 0)
    if ref_price <= 0:
        return None

    expert_contributions = pick.get("expert_contributions") or {}
    expert = _dominant_expert(expert_contributions)
    existing_pred = pick.get("prediction") if isinstance(pick.get("prediction"), dict) else None
    magnitude_source = "preattached"
    if existing_pred and existing_pred.get("predicted_pct") is not None:
        predicted_pct = float(existing_pred["predicted_pct"])
        magnitude_source = str(
            existing_pred.get("magnitude_source") or "preattached"
        )
    else:
        predicted_pct, magnitude_source = _predicted_pct_from_pick(pick, subnet)
    horizon_hours = 1 if horizon_type == "hour" else 4
    if existing_pred and existing_pred.get("horizon_hours") is not None:
        try:
            horizon_hours = int(existing_pred["horizon_hours"])
        except (TypeError, ValueError):
            pass
    now = datetime.now(timezone.utc)

    # Prefer tech signal stamps on the pick root; fall back to nested score shape.
    signal_contributions = pick.get("signal_contributions")
    if not isinstance(signal_contributions, dict):
        nested = expert_contributions.get("signal_contributions")
        signal_contributions = nested if isinstance(nested, dict) else None
    active_signals = pick.get("active_signals")
    if not isinstance(active_signals, list):
        nested_active = expert_contributions.get("active_signals")
        active_signals = nested_active if isinstance(nested_active, list) else []
    signal_impact = pick.get("signal_impact")
    if not isinstance(signal_impact, dict):
        signal_impact = pick.get("signals") if isinstance(pick.get("signals"), dict) else None

    if existing_pred and existing_pred.get("statement"):
        prediction = dict(existing_pred)
        prediction.setdefault("horizon_type", horizon_type)
        prediction.setdefault("expert", expert)
        if signal_contributions and not prediction.get("signal_contributions"):
            prediction["signal_contributions"] = signal_contributions
        if active_signals and not prediction.get("active_signals"):
            prediction["active_signals"] = list(active_signals)
    else:
        prediction = build_prediction_statement(
            sn=subnet,
            predicted_pct=predicted_pct,
            horizon=horizon_hours,
            ref_price=ref_price,
            signal_source=f"council_{horizon_type}_pick",
            expert=expert,
            now=now.replace(tzinfo=None),
            signal_contributions=signal_contributions,
            horizon_type=horizon_type,
            active_signals=active_signals or None,
        )
    prediction["pick_source"] = "council"
    prediction["pick_score"] = pick.get("score")
    prediction["pick_confidence"] = pick.get("confidence", pick.get("final_confidence"))
    prediction["magnitude_source"] = magnitude_source
    prediction["subnet_snapshot"] = _subnet_snapshot(subnet)
    pump_phase = _pump_phase_at_prediction(netuid)
    if pump_phase:
        prediction["phase_at_prediction"] = pump_phase
    try:
        from internal.council.weights import load_impact_strength
        from internal.subnets.impact import impact_profile

        impact = pick.get("impact") if isinstance(pick.get("impact"), dict) else None
        prediction["market_impact"] = impact or impact_profile(subnet)
        prediction["impact_tier"] = prediction["market_impact"].get("tier")
        strength = float(
            prediction["market_impact"].get("strength")
            if prediction["market_impact"].get("strength") is not None
            else load_impact_strength()
        )
        prediction["impact_strength"] = strength
        prediction["impact_strength_at_creation"] = strength
    except Exception:
        pass

    scenario_id = _link_scenario_memory(prediction, subnet, market_context)
    if scenario_id:
        prediction["scenario_id"] = scenario_id

    expert_weights = load_weights()
    prediction["weights_at_creation"] = dict(expert_weights)
    prediction["learning_state_at_creation"] = {
        "council_weights": dict(expert_weights),
        "impact_strength": prediction.get("impact_strength_at_creation"),
        "impact_tier": prediction.get("impact_tier"),
    }
    try:
        from internal.council.prediction_trace import record_prediction_created

        record_prediction_created(
            prediction,
            weights_at_creation=expert_weights,
        )
    except Exception as exc:
        logger.warning("Prediction trace on create failed: %s", exc)

    try:
        from internal.judges.tracker import on_prediction_created

        judge_scores = on_prediction_created(
            prediction,
            signal_impact=signal_impact,
            subnet=subnet,
            expert_weights=expert_weights,
        )
        prediction["judge_scores_at_creation"] = judge_scores
    except Exception as exc:
        logger.warning("Judge on_prediction_created failed: %s", exc)

    if not append_prediction(prediction):
        return None

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
            evidence={
                "pick_score": pick.get("score"),
                "expert": expert,
                "impact_tier": prediction.get("impact_tier"),
                "impact_strength": prediction.get("impact_strength_at_creation"),
            },
        )
        emit_signal_triggered(
            subnet=prediction.get("name"),
            netuid=prediction.get("netuid"),
            signal_name=f"council_{horizon_type}_pick",
            direction=prediction.get("direction"),
            evidence={
                "prediction_id": prediction.get("id"),
                "impact_tier": prediction.get("impact_tier"),
            },
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
        try:
            from internal.analytics.market_drivers import market_driver_tags

            tags = {**tags, **market_driver_tags(subnet)}
        except Exception:
            pass
        created = scenario_memory.add_scenario(
            name=str(prediction.get("name") or subnet.get("name") or f"SN{prediction.get('netuid')}"),
            features={
                **tags,
                "netuid": prediction.get("netuid"),
                "direction": prediction.get("direction"),
                "predicted_pct": prediction.get("predicted_pct"),
                "horizon_type": prediction.get("horizon_type"),
                "expert": prediction.get("expert"),
                "impact_tier": prediction.get("impact_tier"),
                "impact_strength": prediction.get("impact_strength_at_creation"),
                "relative_flow": (prediction.get("market_impact") or {}).get("relative_flow")
                if isinstance(prediction.get("market_impact"), dict)
                else None,
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
        sms[f"last_{horizon_type}_pick"] = {
            "pick": pick,
            "prediction_id": prediction.get("id"),
            "updated_at": prediction.get("created_at"),
        }
        _save_raw(data)
    except Exception as exc:
        logger.warning("Soul-map pick mirror failed: %s", exc)


def record_hold_decision(
    *,
    candidate: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
    horizon_type: str = "day",
) -> None:
    """HOLD still writes the brain — trail + soul-map, no gradeable prediction.

    Confidence gate / empty market must not leave the learning loop silent.
    """
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    cand = candidate if isinstance(candidate, dict) else {}
    sn = cand.get("subnet") if isinstance(cand.get("subnet"), dict) else {}
    name = sn.get("name") or cand.get("name")
    netuid = sn.get("netuid") if sn else cand.get("netuid")
    try:
        conv = float(cand.get("final_confidence", cand.get("confidence", 0)) or 0)
    except (TypeError, ValueError):
        conv = 0.0
    if 0.0 < conv <= 1.0:
        conv_pct = round(conv * 100.0, 1)
    else:
        conv_pct = round(conv, 1)

    try:
        from internal.learning.trail_events import emit_trail_event

        emit_trail_event(
            "conviction_update",
            subnet=name,
            netuid=netuid,
            evidence={
                "action": "HOLD",
                "reason": reason or "No long call published",
                "conviction": conv_pct,
                "horizon_type": horizon_type,
                "gate": "confidence_below_0.45" if cand else "no_subnets",
            },
            signal="council_hold",
            decision="HOLD",
            prediction=reason,
        )
    except Exception as exc:
        logger.warning("HOLD trail emit failed: %s", exc)

    try:
        from internal.council.weights import _load_raw, _save_raw

        data = _load_raw()
        sms = data.setdefault("soul_map_state", {})
        if not isinstance(sms, dict):
            sms = {}
            data["soul_map_state"] = sms
        entry = {
            "action": "HOLD",
            "pick": None,
            "candidate": cand or None,
            "reason": reason,
            "updated_at": now,
        }
        sms[f"last_{horizon_type}_pick"] = entry
        sms[f"last_{horizon_type}_hold"] = entry
        _save_raw(data)
    except Exception as exc:
        logger.warning("HOLD soul-map mirror failed: %s", exc)
