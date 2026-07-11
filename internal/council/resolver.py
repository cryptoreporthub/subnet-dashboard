"""
24h prediction resolver for the modular state-vector Council engine.

Fetches current subnet prices, resolves pending 24h predictions against them,
and classifies each outcome as hit / partial / miss. Resolved predictions are
persisted back to ``data/predictions.json`` and the learning loop is updated
via ``internal.council.weights`` so expert weights reflect resolver feedback.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from internal.council.weights import load_weights, save_weights, nudge_signal_weight

try:
    from internal.judges.tracker import on_prediction_resolved
except Exception:  # pragma: no cover
    def on_prediction_resolved(*_args, **_kwargs):
        return {}

try:
    from internal.council import scenario_memory
except Exception:  # pragma: no cover
    class _FakeScenarioMemory:
        @staticmethod
        def add_scenario(*_args, **_kwargs):
            return {}

        @staticmethod
        def classify_regime(*_args, **_kwargs):
            return "neutral"

    scenario_memory = _FakeScenarioMemory()

PREDICTIONS_PATH = os.path.join("data", "predictions.json")
PRICE_CACHE_PATH = os.path.join("data", "price_cache.json")

_LEARNING_DELTA_CORRECT = 0.02
_LEARNING_DELTA_WRONG = -0.03
_LEARNING_MIN_WEIGHT = 0.1
_LEARNING_MAX_WEIGHT = 2.0

_EXPIRY_GRACE_MULTIPLE = 2.0
_EXPIRY_DEFAULT_HORIZON_HOURS = 24.0

def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)

def fetch_prices(subnets: Optional[List[Dict[str, Any]]] = None) -> Dict[Any, float]:
    prices: Dict[Any, float] = {}

    if subnets is None:
        try:
            from fetchers.taomarketcap import get_all_subnets
            subnets = get_all_subnets()
        except Exception:
            subnets = []

    if subnets:
        for sn in subnets:
            uid = sn.get("netuid")
            price = float(sn.get("price", 0) or 0)
            if uid is not None and price > 0:
                prices[uid] = price

    if len(prices) < 2:
        cache = _load_json(PRICE_CACHE_PATH, {})
        for uid, raw in cache.items():
            if isinstance(raw, dict) and raw.get("candles"):
                candles = raw["candles"]
                if candles:
                    try:
                        close = float(candles[-1].get("close", 0))
                        if close > 0:
                            prices[uid] = close
                    except Exception:
                        pass

    return prices

def classify_outcome(
    prediction: Dict[str, Any],
    current_price: float,
    tolerance: float = 0.5,
) -> str:
    ref = float(prediction.get("reference_price", 0) or 0)
    if ref <= 0 or current_price <= 0:
        return "miss"

    actual_pct = (current_price - ref) / ref * 100
    predicted_pct = float(prediction.get("predicted_pct", 0) or 0)
    if predicted_pct == 0:
        return "miss"

    direction = prediction.get("direction")
    if direction is None:
        direction = "up" if predicted_pct > 0 else "down"

    threshold = predicted_pct * (1 - tolerance)

    if direction == "up":
        if actual_pct >= threshold:
            return "hit"
        if actual_pct > 0:
            return "partial"
        return "miss"

    if actual_pct <= threshold:
        return "hit"
    if actual_pct < 0:
        return "partial"
    return "miss"

def _normalize_expert(prediction: Dict[str, Any]) -> Optional[str]:
    """Map a prediction's expert/signal source to a canonical Council expert."""
    expert = prediction.get("expert") or prediction.get("signal_source")
    if not isinstance(expert, str):
        return None
    expert = expert.lower().strip()

    if expert in {"quant", "hype", "dark_horse", "technical"}:
        return expert

    # Legacy mind-map expert lanes (alpha/beta/gamma) → canonical Council experts
    if expert in {"alpha"}:
        return "quant"
    if expert in {"beta"}:
        return "hype"
    if expert in {"gamma"}:
        return "dark_horse"

    # FIX: "contrarian" maps to dark_horse (legacy signal compatibility)
    if "contrarian" in expert or "dark" in expert or "horse" in expert or "onchain" in expert or "on-chain" in expert or "flow" in expert:
        return "dark_horse"
    if "whale" in expert or "momentum" in expert or "hype" in expert:
        return "hype"
    if "rsi" in expert or "macd" in expert or "technical" in expert:
        return "technical"
    if "quant" in expert or "fundamental" in expert or "yield" in expert:
        return "quant"

    return None

def _nudge_weights(correct: bool, expert: Optional[str]) -> None:
    if not expert:
        return

    delta = _LEARNING_DELTA_CORRECT if correct else _LEARNING_DELTA_WRONG
    weights = load_weights()
    if expert not in weights:
        return

    before = float(weights[expert])
    weights[expert] = max(
        _LEARNING_MIN_WEIGHT,
        min(_LEARNING_MAX_WEIGHT, weights[expert] + delta),
    )
    weights[expert] = round(weights[expert], 4)
    save_weights(weights)
    try:
        from internal.learning.trail_bus import emit_weight_change

        emit_weight_change(
            expert,
            before=before,
            after=float(weights[expert]),
            reason="prediction_resolve",
            correct=correct,
        )
    except Exception:
        pass

def resolve_prediction(
    prediction: Dict[str, Any],
    current_price: float,
    tolerance: float = 0.5,
) -> Dict[str, Any]:
    ref = float(prediction.get("reference_price", 0) or 0)
    actual_pct = 0.0
    if ref > 0 and current_price > 0:
        actual_pct = round((current_price - ref) / ref * 100, 2)

    if abs(actual_pct) > 80:
        prediction["status"] = "expired"
        prediction["outcome"] = "expired"
        prediction["actual_pct"] = None
        return prediction

    outcome = classify_outcome(prediction, current_price, tolerance)
    correct = outcome == "hit"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    prediction["actual_pct"] = actual_pct
    prediction["outcome"] = outcome
    prediction["correct"] = correct
    prediction["status"] = "resolved"
    prediction["resolved_at"] = now
    prediction["resolved_price"] = current_price

    expert = _normalize_expert(prediction)
    if expert:
        prediction["expert"] = expert
        _nudge_weights(correct, expert)
        try:
            from internal.learning.trail_events import emit_prediction_resolved

            emit_prediction_resolved(prediction, expert)
        except Exception:
            pass

    signal_contributions = prediction.get("signal_contributions")
    horizon_type = prediction.get("horizon_type", "hour")
    if isinstance(signal_contributions, dict):
        active_signals = prediction.get("active_signals", [])
        if not active_signals:
            active_signals = [
                k for k, v in signal_contributions.items()
                if isinstance(v, dict) and (v.get("score", 0.5) > 0.55 or v.get("score", 0.5) < 0.45)
            ]
        for signal_name in active_signals:
            try:
                nudge_signal_weight(horizon_type, signal_name, correct)
            except Exception:
                pass

    try:
        features = {
            "direction": prediction.get("direction"),
            "predicted_pct": float(prediction.get("predicted_pct", 0) or 0),
            "actual_pct": actual_pct,
            "outcome": outcome,
            "expert": expert or "unknown",
            "volatility": abs(actual_pct),
        }
        rsi_signal = prediction.get("_rsi_signal")
        volume_signal = prediction.get("_volume_signal")
        if rsi_signal:
            features["rsi"] = rsi_signal
        if volume_signal:
            features["volume"] = volume_signal
        regime = scenario_memory.classify_regime({
            "avg_change_24h": actual_pct,
            "volatility": abs(actual_pct),
        })
        scenario_memory.record_outcome(
            name=prediction.get("name", "unknown"),
            outcome="correct" if correct else "wrong",
            features=features,
            regime=regime,
            scenario_id=prediction.get("scenario_id"),
        )
    except Exception:
        pass

    try:
        on_prediction_resolved(prediction)
    except Exception:
        pass

    return prediction

def _compute_stats(data: Dict[str, Any]) -> Dict[str, Any]:
    resolved = data.get("resolved", [])
    pending = data.get("predictions", [])
    correct = sum(1 for r in resolved if r.get("correct") is True)
    wrong = sum(1 for r in resolved if r.get("correct") is False)
    expired = sum(1 for r in resolved if r.get("outcome") == "expired")
    total = len(resolved) + len(pending)
    stats = {
        "correct": correct,
        "wrong": wrong,
        "expired": expired,
        "pending": len(pending),
        "total": total,
    }
    if correct + wrong > 0:
        stats["accuracy"] = round(correct / (correct + wrong), 3)
    else:
        stats["accuracy"] = 0.0
    return stats

def _scenario_signals_for_subnet(subnet: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(subnet, dict):
        return {}
    out: Dict[str, Any] = {}
    try:
        from internal.council.state_vector import _compute_technical_indicators
        indicators = _compute_technical_indicators(subnet)
        rsi = indicators.get("rsi")
        if isinstance(rsi, dict) and rsi.get("signal"):
            out["rsi"] = rsi.get("signal")
    except Exception:
        pass
    try:
        vol = float(subnet.get("volume", 0) or 0)
        if vol >= 1_000_000:
            out["volume"] = "high"
        elif vol >= 100_000:
            out["volume"] = "medium"
        elif vol > 0:
            out["volume"] = "low"
    except Exception:
        pass
    return out

def _is_expired(
    prediction: Dict[str, Any],
    resolve_at: datetime,
    now: datetime,
    grace_multiple: float = _EXPIRY_GRACE_MULTIPLE,
) -> bool:
    if now < resolve_at:
        return False
    try:
        horizon = float(prediction.get("horizon_hours", 0) or 0)
    except (TypeError, ValueError):
        horizon = 0.0
    if horizon <= 0:
        horizon = _EXPIRY_DEFAULT_HORIZON_HOURS
    grace = timedelta(hours=horizon * grace_multiple)
    return now >= resolve_at + grace

def _expire_prediction(prediction: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    prediction["status"] = "expired"
    prediction["outcome"] = "expired"
    prediction["correct"] = None
    prediction["resolved_at"] = now.isoformat().replace("+00:00", "Z")
    prediction["resolved_price"] = None
    return prediction

def expire_stale_predictions(
    *,
    grace_multiple: float = _EXPIRY_GRACE_MULTIPLE,
) -> Dict[str, Any]:
    data = _load_json(
        PREDICTIONS_PATH,
        {"predictions": [], "resolved": [], "stats": {"correct": 0, "wrong": 0, "pending": 0}},
    )
    predictions: List[Dict[str, Any]] = list(data.get("predictions", []))
    resolved: List[Dict[str, Any]] = list(data.get("resolved", []))
    now = datetime.now(timezone.utc)

    still_pending: List[Dict[str, Any]] = []
    expired_now: List[Dict[str, Any]] = []

    for pred in predictions:
        if not isinstance(pred, dict):
            continue
        try:
            resolve_at = datetime.fromisoformat(
                str(pred.get("resolve_at", "")).replace("Z", "+00:00")
            )
        except Exception:
            _expire_prediction(pred, now)
            resolved.append(pred)
            expired_now.append(pred)
            continue

        if _is_expired(pred, resolve_at, now, grace_multiple):
            _expire_prediction(pred, now)
            resolved.append(pred)
            expired_now.append(pred)
        else:
            still_pending.append(pred)

    data["predictions"] = still_pending
    data["resolved"] = resolved
    data["stats"] = _compute_stats(data)
    _save_json(PREDICTIONS_PATH, data)

    return {
        "expired_now": expired_now,
        "resolved": resolved,
        "pending": still_pending,
        "stats": data["stats"],
    }

def resolve_due_predictions(
    subnets: Optional[List[Dict[str, Any]]] = None,
    *,
    horizon_hours: float = 24.0,
    tolerance: float = 0.5,
) -> Dict[str, Any]:
    """Resolve predictions whose horizon has elapsed and persist the result."""
    data = _load_json(
        PREDICTIONS_PATH,
        {"predictions": [], "resolved": [], "stats": {"correct": 0, "wrong": 0, "pending": 0}},
    )
    predictions: List[Dict[str, Any]] = list(data.get("predictions", []))
    resolved: List[Dict[str, Any]] = list(data.get("resolved", []))
    prices = fetch_prices(subnets)
    subnet_by_uid: Dict[Any, Dict[str, Any]] = {}
    if subnets:
        for sn in subnets:
            if isinstance(sn, dict) and sn.get("netuid") is not None:
                subnet_by_uid[sn.get("netuid")] = sn
    now = datetime.now(timezone.utc)
    still_pending: List[Dict[str, Any]] = []
    resolved_now: List[Dict[str, Any]] = []
    expired_now: List[Dict[str, Any]] = []
    for pred in predictions:
        uid = pred.get("netuid")
        price = prices.get(uid, 0.0)
        try:
            resolve_at = datetime.fromisoformat(
                str(pred.get("resolve_at", "")).replace("Z", "+00:00")
            )
        except Exception:
            resolve_at = now + timedelta(hours=horizon_hours)
        if price > 0 and now >= resolve_at:
            signals = _scenario_signals_for_subnet(subnet_by_uid.get(uid))
            if signals.get("rsi"):
                pred["_rsi_signal"] = signals["rsi"]
            if signals.get("volume"):
                pred["_volume_signal"] = signals["volume"]
            resolve_prediction(pred, price, tolerance)
            pred.pop("_rsi_signal", None)
            pred.pop("_volume_signal", None)
            resolved.append(pred)
            resolved_now.append(pred)
        elif _is_expired(pred, resolve_at, now):
            _expire_prediction(pred, now)
            resolved.append(pred)
            expired_now.append(pred)
        else:
            still_pending.append(pred)
    data["predictions"] = still_pending
    data["resolved"] = resolved
    data["stats"] = _compute_stats(data)
    _save_json(PREDICTIONS_PATH, data)
    try:
        from internal.learning.trail_bus import emit_accuracy_update

        stats = data["stats"]
        emit_accuracy_update(
            accuracy=float(stats.get("accuracy", 0) or 0),
            correct=int(stats.get("correct", 0) or 0),
            wrong=int(stats.get("wrong", 0) or 0),
            pending=int(stats.get("pending", 0) or 0),
            resolved_now=len(resolved_now),
        )
    except Exception:
        pass
    return {
        "resolved_now": resolved_now,
        "expired_now": expired_now,
        "resolved": resolved,
        "pending": still_pending,
        "stats": data["stats"],
    }


def get_resolved_predictions() -> Dict[str, Any]:
    """Return the current resolved prediction ledger without mutating it."""
    data = _load_json(
        PREDICTIONS_PATH,
        {"predictions": [], "resolved": [], "stats": {"correct": 0, "wrong": 0, "pending": 0}},
    )
    data["stats"] = _compute_stats(data)
    return {
        "resolved": data.get("resolved", []),
        "stats": data["stats"],
    }
