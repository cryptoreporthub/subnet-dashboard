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

# Predictions past their ``resolve_at`` with no resolvable price are marked
# ``expired`` once this grace window (as a multiple of the prediction horizon)
# has elapsed, so they do not linger in ``pending`` forever. Expired records
# are excluded from the accuracy denominator (we never learned the outcome).
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

    if expert in {"quant", "hype", "dark_horse", "technical"}:
        return expert

    if "dark" in expert or "horse" in expert or "onchain" in expert or "on-chain" in expert or "flow" in expert:
        return "dark_horse"
    if "whale" in expert or "momentum" in expert or "hype" in expert:
        return "hype"
    if "rsi" in expert or "macd" in expert or "technical" in expert:
        return "technical"
    if "quant" in expert or "fundamental" in expert or "yield" in expert:
        return "quant"

    return None

def _nudge_weights(correct: bool, expert: Optional[str]) -> None:
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

    # Price anomaly guard — if the price move is > 80%, it's likely a unit mismatch
    if abs(actual_pct) > 80:
        logger.warning(f"Price anomaly detected: {actual_pct}% — skipping resolution")
        prediction["status"] = "expired"
        prediction["outcome"] = "expired"
        prediction["actual_pct"] = None
        # Don't update weights for this prediction
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

    # Nudge per-signal weights when signal_contributions are available.
    signal_contributions = prediction.get("signal_contributions")
    horizon_type = prediction.get("horizon_type", "hour")
    if isinstance(signal_contributions, dict):
        active_signals = prediction.get("active_signals", [])
        if not active_signals:
            # Derive active signals from contributions if not pre-computed.
            active_signals = [
                k for k, v in signal_contributions.items()
                if isinstance(v, dict) and (v.get("score", 0.5) > 0.55 or v.get("score", 0.5) < 0.45)
            ]
        for signal_name in active_signals:
            try:
                nudge_signal_weight(horizon_type, signal_name, correct)
            except Exception:
                pass

    # Record scenario in regime-aware memory for learning. Outcomes are wired
    # back to the originating scenario record (created when the prediction was
    # minted) via ``record_outcome`` so the learning loop grades the same
    # scenario in place rather than minting a duplicate on every resolution.
    try:
        features = {
            "direction": prediction.get("direction"),
            "predicted_pct": float(prediction.get("predicted_pct", 0) or 0),
            "actual_pct": actual_pct,
            "outcome": outcome,
            "expert": expert or "unknown",
            "volatility": abs(actual_pct),
        }
        # Surface RSI and volume signals when precomputed by the caller (the
        # batch resolver looks up the subnet and derives these so the recorded
        # scenario carries regime + rsi + volume, not just the move magnitude).
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
    # ``correct`` is True/False for resolved predictions and ``None`` for
    # expired ones (no outcome could be determined). Expired records are
    # tracked separately and excluded from the accuracy denominator so a
    # missing price feed never silently drags accuracy toward zero.
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
    """Derive RSI and volume signals for a subnet to attach to recorded scenarios.

    Returns a dict with optional ``rsi`` (overbought/oversold/neutral) and
    ``volume`` (high/medium/low) signals. Best-effort: any failure yields an
    empty dict so the resolver never crashes on scenario enrichment.
    """
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
        # Bucket raw 24h volume into high/medium/low. Thresholds are deliberately
        # coarse — this is a regime tag for memory, not a precise signal.
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
    """Return True if a due prediction with no price has aged past its grace window.

    A prediction is only eligible for expiry once it is past ``resolve_at``
    (so not-yet-due predictions are never expired) AND the grace window — a
    multiple of the prediction's own horizon — has elapsed, giving the price
    feed a fair chance to recover before we retire the record.
    """
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
    """Retire a prediction as ``expired`` (no verifiable outcome).

    Expired predictions carry ``correct=None`` and ``outcome="expired"`` so
    they are excluded from the accuracy denominator. Expert weights are NOT
    nudged — we never learned whether the prediction was right.
    """
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
    """Retire pending predictions that are past due with no resolvable price.

    This is the safety net for the scheduled resolver: predictions whose
    ``resolve_at`` has passed but for which no price could ever be fetched
    (delisted subnet, persistent feed outage, corrupt record) are moved out
    of ``pending`` into ``resolved`` as ``expired`` so the registry does not
    accumulate ungradeable records forever. Returns a summary of the pass.
    """
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
            # Corrupt/unparseable record: retire it as expired so a bad row
            # can never block the resolver loop.
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
    # Index subnets by netuid so we can enrich each resolved prediction with
    # real RSI/volume signals for the scenario-memory record.
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
            # Attach current RSI/volume signals so the scenario recorded on
            # resolution reflects real market state, not just the move size.
            signals = _scenario_signals_for_subnet(subnet_by_uid.get(uid))
            if signals.get("rsi"):
                pred["_rsi_signal"] = signals["rsi"]
            if signals.get("volume"):
                pred["_volume_signal"] = signals["volume"]
            resolve_prediction(pred, price, tolerance)
            # Don't persist the transient enrichment keys.
            pred.pop("_rsi_signal", None)
            pred.pop("_volume_signal", None)
            resolved.append(pred)
            resolved_now.append(pred)
        elif _is_expired(pred, resolve_at, now):
            # Past due AND no price available AND the grace window has elapsed:
            # we will never be able to grade this prediction, so retire it as
            # ``expired`` rather than letting it sit in ``pending`` forever.
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
