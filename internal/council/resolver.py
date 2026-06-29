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

from internal.council.weights import load_weights, save_weights

PREDICTIONS_PATH = os.path.join("data", "predictions.json")
PRICE_CACHE_PATH = os.path.join("data", "price_cache.json")

_LEARNING_DELTA_CORRECT = 0.02
_LEARNING_DELTA_WRONG = -0.03
_LEARNING_MIN_WEIGHT = 0.1
_LEARNING_MAX_WEIGHT = 2.0


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
    """Return a ``netuid -> price`` map from live subnets or the price cache."""
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

    # Fallback to price cache if live fetch is sparse.
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
    """Classify a prediction as ``hit``, ``partial`` or ``miss``."""
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

    # direction == "down"
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

    # Direct names used by weights.py.
    if expert in {"quant", "hype", "contrarian", "technical"}:
        return expert

    # Common signal-source aliases.
    if "sell" in expert or "bear" in expert or "contrarian" in expert:
        return "contrarian"
    if "whale" in expert or "momentum" in expert or "hype" in expert:
        return "hype"
    if "rsi" in expert or "macd" in expert or "technical" in expert:
        return "technical"
    if "quant" in expert or "fundamental" in expert or "yield" in expert:
        return "quant"

    return None


def _nudge_weights(
    prediction: Dict[str, Any],
    correct: bool,
    expert: Optional[str],
) -> None:
    """Update Council expert weights through the learning loop."""
    if not expert:
        return

    delta = _LEARNING_DELTA_CORRECT if correct else _LEARNING_DELTA_WRONG
    weights = load_weights()
    if expert not in weights:
        return

    weights[expert] = max(
        _LEARNING_MIN_WEIGHT,
        min(_LEARNING_MAX_WEIGHT, weights[expert] + delta),
    )
    weights[expert] = round(weights[expert], 4)
    save_weights(weights)


def resolve_prediction(
    prediction: Dict[str, Any],
    current_price: float,
    tolerance: float = 0.5,
) -> Dict[str, Any]:
    """Resolve a single prediction in place and return it."""
    ref = float(prediction.get("reference_price", 0) or 0)
    actual_pct = 0.0
    if ref > 0 and current_price > 0:
        actual_pct = round((current_price - ref) / ref * 100, 2)

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
        _nudge_weights(prediction, correct, expert)

    return prediction


def _compute_stats(data: Dict[str, Any]) -> Dict[str, Any]:
    resolved = data.get("resolved", [])
    pending = data.get("predictions", [])
    correct = sum(1 for r in resolved if r.get("correct"))
    wrong = sum(1 for r in resolved if not r.get("correct"))
    total = len(resolved) + len(pending)
    stats = {
        "correct": correct,
        "wrong": wrong,
        "pending": len(pending),
        "total": total,
    }
    if correct + wrong > 0:
        stats["accuracy"] = round(correct / (correct + wrong), 3)
    else:
        stats["accuracy"] = 0.0
    return stats


def resolve_due_predictions(
    subnets: Optional[List[Dict[str, Any]]] = None,
    *,
    horizon_hours: float = 24.0,
    tolerance: float = 0.5,
) -> Dict[str, Any]:
    """Resolve predictions whose horizon has elapsed and persist the result.

    Returns a dict with ``resolved_now``, ``resolved``, ``pending`` and
    ``stats`` so callers can surface newly resolved predictions without
    re-reading the store.
    """
    data = _load_json(
        PREDICTIONS_PATH,
        {"predictions": [], "resolved": [], "stats": {"correct": 0, "wrong": 0, "pending": 0}},
    )
    predictions: List[Dict[str, Any]] = list(data.get("predictions", []))
    resolved: List[Dict[str, Any]] = list(data.get("resolved", []))

    prices = fetch_prices(subnets)
    now = datetime.now(timezone.utc)

    still_pending: List[Dict[str, Any]] = []
    resolved_now: List[Dict[str, Any]] = []

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
            resolve_prediction(pred, price, tolerance)
            resolved.append(pred)
            resolved_now.append(pred)
        else:
            still_pending.append(pred)

    data["predictions"] = still_pending
    data["resolved"] = resolved
    data["stats"] = _compute_stats(data)
    _save_json(PREDICTIONS_PATH, data)

    return {
        "resolved_now": resolved_now,
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
