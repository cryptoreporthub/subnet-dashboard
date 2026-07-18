"""
24h prediction resolver for the modular state-vector Council engine.

Phase J: horizon-end pricing, expire-late, direction-only grading, symmetric
weights, atomic ledger resolution, and dedupe before resolve.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

from internal.council.deduplication import dedupe_predictions
from internal.council.grading import (
    classify_outcome_direction_only,
    compute_actual_pct,
    direction_correct,
)
from internal.council.price_reference import CANDLE_LOOKUP_MINUTES, price_at_resolve_at
from internal.council.watchdog import check_resolver_watchdog
from internal.council.weights import load_weights, nudge_impact_strength, nudge_signal_weight, save_weights

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

        @staticmethod
        def record_outcome(*_args, **_kwargs):
            return None

    scenario_memory = _FakeScenarioMemory()

PREDICTIONS_PATH = os.path.join("data", "predictions.json")
PRICE_CACHE_PATH = os.path.join("data", "price_cache.json")

_LEARNING_DELTA_CORRECT = 0.02
_LEARNING_DELTA_WRONG = -0.02
_LEARNING_MIN_WEIGHT = 0.3
_LEARNING_MAX_WEIGHT = 2.0

_EXPIRY_GRACE_MULTIPLE = 2.0
_EXPIRY_DEFAULT_HORIZON_HOURS = 24.0

_replay_mode: ContextVar[bool] = ContextVar("resolver_replay_mode", default=False)


@contextmanager
def replay_mode(enabled: bool = True) -> Iterator[None]:
    token = _replay_mode.set(enabled)
    try:
        yield
    finally:
        _replay_mode.reset(token)


def _in_replay_mode() -> bool:
    return _replay_mode.get()


def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
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
    """Direction-only grading (Phase J4). ``tolerance`` kept for API compatibility."""
    ref = float(prediction.get("reference_price", 0) or 0)
    if ref <= 0 or current_price <= 0:
        return "miss"
    actual_pct = compute_actual_pct(ref, current_price)
    return classify_outcome_direction_only(prediction, actual_pct)


def _normalize_expert(prediction: Dict[str, Any]) -> Optional[str]:
    expert = prediction.get("expert") or prediction.get("signal_source")
    if not isinstance(expert, str):
        return None
    expert = expert.lower().strip()

    if expert in {"quant", "hype", "dark_horse", "technical"}:
        return expert

    if expert in {"alpha"}:
        return "quant"
    if expert in {"beta"}:
        return "hype"
    if expert in {"gamma"}:
        return "dark_horse"

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
    if _in_replay_mode() or not expert:
        return

    from internal.council.weights import load_weights, nudge_expert

    before = float(load_weights().get(expert, 1.0))
    after = nudge_expert(expert, bool(correct))
    if after is None:
        return
    try:
        from internal.learning.trail_bus import emit_weight_change

        emit_weight_change(
            expert,
            before=before,
            after=float(after),
            reason="prediction_resolve",
            correct=correct,
        )
    except Exception:
        pass


def _parse_resolve_at(prediction: Dict[str, Any]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(
            str(prediction.get("resolve_at", "")).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except Exception:
        return None


def _horizon_hours(prediction: Dict[str, Any]) -> float:
    try:
        horizon = float(prediction.get("horizon_hours", 0) or 0)
    except (TypeError, ValueError):
        horizon = 0.0
    return horizon if horizon > 0 else _EXPIRY_DEFAULT_HORIZON_HOURS


def _is_expired(
    prediction: Dict[str, Any],
    resolve_at: datetime,
    now: datetime,
    grace_multiple: float = _EXPIRY_GRACE_MULTIPLE,
) -> bool:
    if now < resolve_at:
        return False
    grace = timedelta(hours=_horizon_hours(prediction) * grace_multiple)
    return now >= resolve_at + grace


def _expire_prediction(prediction: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    prediction["status"] = "expired"
    prediction["outcome"] = "expired"
    prediction["correct"] = None
    prediction["resolved_at"] = now.isoformat().replace("+00:00", "Z")
    prediction["resolved_price"] = None
    prediction["actual_pct"] = None
    return prediction


def _mark_ungradeable(prediction: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    prediction["status"] = "ungradeable"
    prediction["outcome"] = "ungradeable"
    prediction["correct"] = None
    prediction["resolved_at"] = now.isoformat().replace("+00:00", "Z")
    prediction["resolved_price"] = None
    prediction["actual_pct"] = None
    return prediction


def lookup_horizon_price(
    prediction: Dict[str, Any],
    *,
    resolve_at: datetime,
    now: datetime,
    live_prices: Optional[Dict[Any, float]] = None,
    cache_path: Optional[str] = None,
) -> Tuple[str, float, Dict[str, Any]]:
    """Return (status, price, meta). status: ok | ungradeable."""
    cache = _load_json(cache_path or PRICE_CACHE_PATH, {})
    status, price, meta = price_at_resolve_at(
        prediction.get("netuid"),
        resolve_at,
        cache=cache,
    )
    if status == "ok" and price > 0:
        return status, price, meta

    live_prices = live_prices or {}
    uid = prediction.get("netuid")
    live = float(live_prices.get(uid, 0) or 0)
    # ponytail: widen live fallback to 60m + 2m — hour picks miss 15m candles; +120s covers tick lag
    live_window_sec = max(CANDLE_LOOKUP_MINUTES * 60, 3600) + 120
    if live > 0 and abs((now - resolve_at).total_seconds()) <= live_window_sec:
        meta = {
            "price_source": "live_oracle",
            "price_lag_seconds": int(abs((now - resolve_at).total_seconds())),
            "candles_in_window": meta.get("candles_in_window", 0),
        }
        return "ok", live, meta

    return "ungradeable", 0.0, meta


def _apply_price_meta(prediction: Dict[str, Any], meta: Dict[str, Any], price: float) -> None:
    prediction["resolved_price"] = price
    prediction["price_source"] = meta.get("price_source")
    prediction["price_lag_seconds"] = meta.get("price_lag_seconds")


def _record_scenario_outcome(
    prediction: Dict[str, Any],
    actual_pct: float,
    outcome: str,
    correct: bool,
    expert: Optional[str],
) -> None:
    try:
        features = {
            "direction": prediction.get("direction"),
            "predicted_pct": float(prediction.get("predicted_pct", 0) or 0),
            "actual_pct": actual_pct,
            "outcome": outcome,
            "expert": expert or "unknown",
            "volatility": abs(actual_pct),
            "impact_tier": prediction.get("impact_tier"),
            "impact_strength_at_creation": prediction.get("impact_strength_at_creation"),
            "impact_strength_after": prediction.get("impact_strength_after"),
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


def _snapshot_is_thin(snap: Any) -> bool:
    if not isinstance(snap, dict) or not snap:
        return True
    if snap.get("price") in (None, ""):
        return True
    if snap.get("price_change_24h") is None and snap.get("price_change_7d") is None:
        return True
    return False


def _lookup_subnet_row(netuid: Any) -> Optional[Dict[str, Any]]:
    if netuid is None:
        return None
    try:
        from internal.subnets.feed import get_council_subnet_feed

        rows, _source = get_council_subnet_feed()
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("netuid") == netuid or str(row.get("netuid")) == str(netuid):
                return row
    except Exception:
        pass
    return None


def _ensure_subnet_snapshot(
    prediction: Dict[str, Any],
    *,
    subnet_row: Optional[Dict[str, Any]] = None,
) -> bool:
    """Backfill subnet_snapshot at resolve when creation-time context was missing."""
    from internal.learning.prediction_loop import _subnet_snapshot

    existing = prediction.get("subnet_snapshot")
    if not _snapshot_is_thin(existing):
        return False

    row = subnet_row if isinstance(subnet_row, dict) else _lookup_subnet_row(prediction.get("netuid"))
    if not row:
        return False

    fresh = _subnet_snapshot(row)
    if fresh.get("price") in (None, "") and prediction.get("reference_price") not in (None, ""):
        fresh["price"] = prediction.get("reference_price")

    if not isinstance(existing, dict) or not existing:
        prediction["subnet_snapshot"] = fresh
        prediction["subnet_snapshot_source"] = "resolve_backfill"
        return True

    merged = dict(existing)
    for key, value in fresh.items():
        if merged.get(key) in (None, "") and value not in (None, ""):
            merged[key] = value
    prediction["subnet_snapshot"] = merged
    prediction["subnet_snapshot_source"] = "resolve_merge"
    return True


def atomic_finalize_resolution(
    prediction: Dict[str, Any],
    *,
    actual_pct: float,
    outcome: str,
    correct: Optional[bool],
    resolved_price: float,
    resolved_at: str,
    price_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """J3: one event updates prediction, judges, and trace."""
    prediction["actual_pct"] = actual_pct
    prediction["outcome"] = outcome
    prediction["correct"] = correct
    prediction["status"] = "resolved" if outcome == "hit" or outcome == "miss" else prediction.get("status", "resolved")
    if outcome in {"hit", "miss"}:
        prediction["status"] = "resolved"
    prediction["resolved_at"] = resolved_at
    prediction["resolved_price"] = resolved_price
    if price_meta:
        prediction["price_source"] = price_meta.get("price_source")
        prediction["price_lag_seconds"] = price_meta.get("price_lag_seconds")

    try:
        on_prediction_resolved(prediction)
    except Exception:
        pass

    try:
        from internal.council.prediction_trace import record_prediction_resolved

        record_prediction_resolved(prediction)
    except Exception:
        pass

    try:
        from internal.learning.trail_events import emit_prediction_resolved

        emit_prediction_resolved(prediction, prediction.get("expert"))
    except Exception:
        pass

    try:
        from internal.council import pick_history

        pick_history.finalize_from_prediction(prediction)
    except Exception:
        pass

    return prediction


def resolve_prediction(
    prediction: Dict[str, Any],
    current_price: Optional[float] = None,
    tolerance: float = 0.5,
) -> Dict[str, Any]:
    """Resolve using an explicit price (tests) or horizon lookup when omitted."""
    now = datetime.now(timezone.utc)
    if current_price is not None and current_price > 0:
        ref = float(prediction.get("reference_price", 0) or 0)
        actual_pct = compute_actual_pct(ref, current_price)
        outcome = classify_outcome_direction_only(prediction, actual_pct)
        correct = direction_correct(prediction, actual_pct)
        resolved_at = now.isoformat().replace("+00:00", "Z")
        expert = _normalize_expert(prediction)
        if expert:
            prediction["expert"] = expert
            _nudge_weights(bool(correct), expert)
        _ensure_subnet_snapshot(prediction)
        # Impact dial before finalize so prediction_resolved trail includes after value.
        _nudge_impact_strength(prediction, bool(correct))
        atomic_finalize_resolution(
            prediction,
            actual_pct=actual_pct,
            outcome=outcome,
            correct=correct,
            resolved_price=current_price,
            resolved_at=resolved_at,
        )
        _record_scenario_outcome(prediction, actual_pct, outcome, bool(correct), expert)
        _nudge_signal_weights(prediction, bool(correct))
        return prediction
    return resolve_prediction_at_horizon(prediction, now=now)


def _nudge_signal_weights(prediction: Dict[str, Any], correct: bool) -> None:
    if _in_replay_mode():
        return
    signal_contributions = prediction.get("signal_contributions")
    horizon_type = prediction.get("horizon_type", "hour")
    if not isinstance(signal_contributions, dict):
        return
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


def resolve_prediction_at_horizon(
    prediction: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
    live_prices: Optional[Dict[Any, float]] = None,
    grace_multiple: float = _EXPIRY_GRACE_MULTIPLE,
    subnet_row: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Grade at ``resolve_at`` price; expire late rows; never use stale live price."""
    now = now or datetime.now(timezone.utc)
    resolve_at = _parse_resolve_at(prediction)
    if resolve_at is None:
        return _expire_prediction(prediction, now)

    if _is_expired(prediction, resolve_at, now, grace_multiple):
        return _expire_prediction(prediction, now)

    if now < resolve_at:
        prediction["status"] = "pending"
        return prediction

    status, price, meta = lookup_horizon_price(
        prediction,
        resolve_at=resolve_at,
        now=now,
        live_prices=live_prices,
    )
    if status != "ok" or price <= 0:
        if _is_expired(prediction, resolve_at, now, grace_multiple):
            return _expire_prediction(prediction, now)
        prediction["status"] = "pending"
        return prediction

    ref = float(prediction.get("reference_price", 0) or 0)
    actual_pct = compute_actual_pct(ref, price)
    outcome = classify_outcome_direction_only(prediction, actual_pct)
    correct = direction_correct(prediction, actual_pct)
    resolved_at = resolve_at.isoformat().replace("+00:00", "Z")
    expert = _normalize_expert(prediction)
    if expert:
        prediction["expert"] = expert
        _nudge_weights(bool(correct), expert)

    _ensure_subnet_snapshot(prediction, subnet_row=subnet_row)
    # Impact dial before finalize so prediction_resolved trail includes after value.
    _nudge_impact_strength(prediction, bool(correct))
    atomic_finalize_resolution(
        prediction,
        actual_pct=actual_pct,
        outcome=outcome,
        correct=correct,
        resolved_price=price,
        resolved_at=resolved_at,
        price_meta=meta,
    )
    _record_scenario_outcome(prediction, actual_pct, outcome, bool(correct), expert)
    _nudge_signal_weights(prediction, bool(correct))
    return prediction


def _nudge_impact_strength(prediction: Dict[str, Any], correct: bool) -> None:
    """Let SimiVision dial impact_strength when size tilt over/under-corrects."""
    if _in_replay_mode():
        return
    try:
        from internal.council.weights import load_impact_strength
        from internal.learning.trail_bus import emit_impact_strength_change

        impact = prediction.get("market_impact") or prediction.get("impact") or {}
        tier = None
        if isinstance(impact, dict):
            tier = impact.get("tier")
        if not tier:
            tier = prediction.get("impact_tier")
        before = float(load_impact_strength())
        after = float(nudge_impact_strength(bool(correct), tier=tier))
        prediction["impact_strength_after"] = after
        if abs(after - before) >= 1e-9:
            emit_impact_strength_change(
                before=before,
                after=after,
                correct=bool(correct),
                tier=str(tier) if tier else None,
                prediction_id=str(prediction.get("id") or "") or None,
            )
    except Exception:
        pass


def _compute_stats(data: Dict[str, Any]) -> Dict[str, Any]:
    resolved = data.get("resolved", [])
    pending = data.get("predictions", [])
    gradable = [
        r for r in resolved
        if r.get("outcome") not in {"duplicate", "expired", "ungradeable"}
        and r.get("correct") is not None
    ]
    correct = sum(1 for r in gradable if r.get("correct") is True)
    wrong = sum(1 for r in gradable if r.get("correct") is False)
    expired = sum(1 for r in resolved if r.get("outcome") == "expired")
    duplicates = sum(1 for r in resolved if r.get("outcome") == "duplicate")
    total = len(resolved) + len(pending)
    stats: Dict[str, Any] = {
        "correct": correct,
        "wrong": wrong,
        "expired": expired,
        "duplicate": duplicates,
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
        resolve_at = _parse_resolve_at(pred)
        if resolve_at is None or _is_expired(pred, resolve_at, now, grace_multiple):
            _expire_prediction(pred, now)
            resolved.append(pred)
            expired_now.append(pred)
        else:
            still_pending.append(pred)

    data["predictions"] = still_pending
    data["resolved"] = resolved
    data["stats"] = _compute_stats(data)
    data["watchdog"] = check_resolver_watchdog(still_pending, now=now)
    _save_json(PREDICTIONS_PATH, data)

    return {
        "expired_now": expired_now,
        "resolved": resolved,
        "pending": still_pending,
        "stats": data["stats"],
        "watchdog": data["watchdog"],
    }


def _merge_regraded_resolved(resolved: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Re-sync rows regrade_expired_predictions updated on disk (RF-3 follow-up)."""
    fresh = _load_json(PREDICTIONS_PATH, {}).get("resolved") or []
    by_id = {
        str(row.get("id")): row
        for row in fresh
        if isinstance(row, dict) and row.get("id")
    }
    if not by_id:
        return resolved
    return [
        by_id[str(row.get("id"))] if row.get("id") and str(row.get("id")) in by_id else row
        for row in resolved
    ]


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
    raw_pending: List[Dict[str, Any]] = list(data.get("predictions", []))
    resolved: List[Dict[str, Any]] = list(data.get("resolved", []))
    pending, duplicate_rows = dedupe_predictions(raw_pending)
    resolved.extend(duplicate_rows)

    prices = fetch_prices(subnets)
    regraded_expired = regrade_expired_predictions(live_prices=prices)
    if int(regraded_expired.get("regraded") or 0) > 0:
        resolved = _merge_regraded_resolved(resolved)
    subnet_by_uid: Dict[Any, Dict[str, Any]] = {}
    if subnets:
        for sn in subnets:
            if isinstance(sn, dict) and sn.get("netuid") is not None:
                subnet_by_uid[sn.get("netuid")] = sn
    now = datetime.now(timezone.utc)
    still_pending: List[Dict[str, Any]] = []
    resolved_now: List[Dict[str, Any]] = []
    expired_now: List[Dict[str, Any]] = []

    for pred in pending:
        uid = pred.get("netuid")
        resolve_at = _parse_resolve_at(pred)
        if resolve_at is None:
            _expire_prediction(pred, now)
            resolved.append(pred)
            expired_now.append(pred)
            continue

        if _is_expired(pred, resolve_at, now):
            _expire_prediction(pred, now)
            resolved.append(pred)
            expired_now.append(pred)
            continue

        if now >= resolve_at:
            signals = _scenario_signals_for_subnet(subnet_by_uid.get(uid))
            if signals.get("rsi"):
                pred["_rsi_signal"] = signals["rsi"]
            if signals.get("volume"):
                pred["_volume_signal"] = signals["volume"]
            before_status = pred.get("status")
            resolve_prediction_at_horizon(
                pred, now=now, live_prices=prices, subnet_row=subnet_by_uid.get(uid)
            )
            pred.pop("_rsi_signal", None)
            pred.pop("_volume_signal", None)
            if pred.get("status") == "pending" and before_status == "pending":
                still_pending.append(pred)
            elif pred.get("status") == "expired":
                resolved.append(pred)
                expired_now.append(pred)
            elif pred.get("status") in {"resolved", "ungradeable"}:
                resolved.append(pred)
                resolved_now.append(pred)
            else:
                still_pending.append(pred)
        else:
            still_pending.append(pred)

    data["predictions"] = still_pending
    data["resolved"] = resolved
    data["stats"] = _compute_stats(data)
    data["watchdog"] = check_resolver_watchdog(still_pending, now=now)
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
        "duplicates_now": duplicate_rows,
        "regraded_expired": regraded_expired,
        "resolved": resolved,
        "pending": still_pending,
        "stats": data["stats"],
        "watchdog": data["watchdog"],
    }


def regrade_expired_predictions(
    *,
    live_prices: Optional[Dict[Any, float]] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """Retry grading expired rows when price cache now has horizon candles (RF-3)."""
    data = _load_json(
        PREDICTIONS_PATH,
        {"predictions": [], "resolved": [], "stats": {}},
    )
    resolved: List[Dict[str, Any]] = list(data.get("resolved", []))
    regraded: List[Dict[str, Any]] = []
    attempted = 0

    for idx, pred in enumerate(resolved):
        if attempted >= limit:
            break
        if not isinstance(pred, dict) or pred.get("outcome") != "expired":
            continue
        resolve_at = _parse_resolve_at(pred)
        if resolve_at is None:
            continue
        attempted += 1
        copy = dict(pred)
        copy["status"] = "pending"
        copy.pop("outcome", None)
        copy.pop("resolved_at", None)
        attempt_now = resolve_at + timedelta(minutes=5)
        result = resolve_prediction_at_horizon(
            copy,
            now=attempt_now,
            live_prices=live_prices,
        )
        if result.get("outcome") in {"duplicate", "expired", "ungradeable"}:
            continue
        if result.get("actual_pct") is None:
            continue
        resolved[idx] = result
        regraded.append(result)

    if regraded:
        data["resolved"] = resolved
        data["stats"] = _compute_stats(data)
        _save_json(PREDICTIONS_PATH, data)

    return {
        "attempted": attempted,
        "regraded": len(regraded),
        "stats": data.get("stats", _compute_stats(data)),
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
