"""Phase J6 — prediction create/resolve trace records."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from internal.council.grading import prediction_direction


def _signals_from_prediction(prediction: Dict[str, Any]) -> List[Dict[str, Any]]:
    signals: List[Dict[str, Any]] = []
    contributions = prediction.get("signal_contributions")
    if isinstance(contributions, dict):
        for name, raw in contributions.items():
            payload = raw if isinstance(raw, dict) else {"score": raw}
            signals.append({"type": "pick_signal", "source": str(name), "payload": payload})
    active = prediction.get("active_signals")
    if isinstance(active, list):
        for name in active:
            if isinstance(name, str):
                signals.append({"type": "pick_signal", "source": name, "payload": {}})
    if not signals and prediction.get("signal_source"):
        signals.append(
            {
                "type": "pick_signal",
                "source": str(prediction.get("signal_source")),
                "payload": {},
            }
        )
    return signals


def build_trace_payload(
    prediction: Dict[str, Any],
    *,
    event: str,
    weights_at_creation: Optional[Dict[str, float]] = None,
    regime: Optional[str] = None,
) -> Dict[str, Any]:
    """Minimum SciWeave trace schema for create + resolve events."""
    return {
        "prediction_id": prediction.get("id"),
        "event": event,
        "signals": _signals_from_prediction(prediction),
        "expert": prediction.get("expert") or prediction.get("signal_source"),
        "weights_at_creation": weights_at_creation or prediction.get("weights_at_creation"),
        "impact_strength_at_creation": prediction.get("impact_strength_at_creation"),
        "impact_tier": prediction.get("impact_tier"),
        "market_impact": prediction.get("market_impact"),
        "learning_state_at_creation": prediction.get("learning_state_at_creation"),
        "regime": regime or prediction.get("regime"),
        "reference_price": prediction.get("reference_price"),
        "resolved_price": prediction.get("resolved_price"),
        "horizon_hours": prediction.get("horizon_hours"),
        "created_at": prediction.get("created_at"),
        "resolved_at": prediction.get("resolved_at"),
        "resolve_at": prediction.get("resolve_at"),
        "actual_pct": prediction.get("actual_pct"),
        "outcome": prediction.get("outcome"),
        "direction": prediction_direction(prediction),
        "price_source": prediction.get("price_source"),
        "price_lag_seconds": prediction.get("price_lag_seconds"),
    }


def record_prediction_created(
    prediction: Dict[str, Any],
    *,
    weights_at_creation: Optional[Dict[str, float]] = None,
    regime: Optional[str] = None,
    store_path: Optional[str] = None,
) -> Dict[str, Any]:
    payload = build_trace_payload(
        prediction,
        event="created",
        weights_at_creation=weights_at_creation,
        regime=regime,
    )
    try:
        from internal.trace.engine import record_lineage

        return record_lineage(
            decision_type="prediction_create",
            decision=payload,
            signals=payload.get("signals") or [],
            subnet=prediction.get("name"),
            netuid=prediction.get("netuid"),
            store_path=store_path,
            emit_trail=False,
            update_soul_map=False,
        )
    except Exception:
        return payload


def record_prediction_resolved(
    prediction: Dict[str, Any],
    *,
    store_path: Optional[str] = None,
) -> Dict[str, Any]:
    payload = build_trace_payload(prediction, event="resolved")
    try:
        from internal.trace.engine import record_lineage

        return record_lineage(
            decision_type="prediction_resolve",
            decision=payload,
            signals=payload.get("signals") or [],
            subnet=prediction.get("name"),
            netuid=prediction.get("netuid"),
            store_path=store_path,
            emit_trail=False,
            update_soul_map=False,
        )
    except Exception:
        return payload
