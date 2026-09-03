"""24h prediction resolver for the modular state-vector Council engine.

Phase J: horizon-end pricing, expire-late, direction-only grading, symmetric
weights, atomic ledger resolution, and dedupe before resolve.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

from internal.council.deduplication import dedupe_predictions
from internal.council.capture import (
    CaptureResult,
    capture_mode_enabled,
    capture_nudge_correct,
    nudge_multiplier,
    stamp_capture_fields,
)
from internal.council.grading import (
    classify_outcome_direction_only,
    compute_actual_pct,
    grade_prediction,
    is_price_unit_mismatch,
    is_pump_desk_claim,
    is_pump_lead,
)
from internal.council.price_reference import (
    CANDLE_LOOKUP_MINUTES,
    hydrate_candles_for_netuid,
    hydrate_candles_for_netuid_historical,
    price_at_resolve_at,
    resolver_hydration_budget,
)
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

# Cold-cache alert: warn when price_data_unavailable / total_resolved exceeds this ratio.
# Override with COLD_CACHE_ALERT_RATIO env var (float in [0, 1], e.g. "0.05" for 5%).
_COLD_CACHE_ALERT_RATIO_DEFAULT = 0.05


def _parse_cold_cache_alert_ratio(raw: Optional[str]) -> float:
    """Parse and validate COLD_CACHE_ALERT_RATIO; fall back to default on bad input."""
    default = _COLD_CACHE_ALERT_RATIO_DEFAULT
    if not raw:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "COLD_CACHE_ALERT_RATIO=%r is not a valid float; using default %.4f",
            raw,
            default,
        )
        return default
    import math
    if not math.isfinite(value) or value < 0 or value > 1:
        logger.warning(
            "COLD_CACHE_ALERT_RATIO=%r is out of range [0, 1] or non-finite; using default %.4f",
            raw,
            default,
        )
        return default
    return value


COLD_CACHE_ALERT_RATIO: float = _parse_cold_cache_alert_ratio(
    os.environ.get("COLD_CACHE_ALERT_RATIO")
)

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


def _skip_council_learning(prediction: Dict[str, Any]) -> bool:
    """Pump desk + HOLD counterfactual shadows must not nudge council weights."""
    if is_pump_desk_claim(prediction):
        return True
    return bool(prediction.get("shadow") or prediction.get("counterfactual"))


def _already_graded(prediction: Dict[str, Any]) -> bool:
    """True when this row already resolved — a second pass must not re-nudge."""
    from internal.council.capture import BANDS

    if prediction.get("band") in BANDS:
        return True
    if prediction.get("correct") is not None:
        return True
    return str(prediction.get("status") or "") == "resolved"


def _is_shadow(prediction: Dict[str, Any]) -> bool:
    return bool(prediction.get("shadow") or prediction.get("counterfactual"))


def _load_json(path: str, default: Any) -> Any:
    now = datetime.now(timezone.utc)
    file_bytes = 0
    mtime_iso: Optional[str] = None
    mtime_age_seconds = 0.0
    parse_scope = path
    partial_parse = True
    result: Any = default
    try:
        stat = os.stat(path)
        mtime_iso = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        mtime_age_seconds = max(0.0, now.timestamp() - stat.st_mtime)
        file_bytes = stat.st_size
        with open(path, "r", encoding="utf-8") as f:
            result = json.load(f)
        partial_parse = False
        if isinstance(result, dict):
            parse_scope = path + ":" + "|".join(sorted(str(k) for k in result.keys()))
        else:
            parse_scope = f"{path}:non_dict"
    except Exception:
        pass
    logger.info(
        "resolver_read_path %s",
        json.dumps(
            {
                "file_bytes": file_bytes,
                "mtime": mtime_iso,
                "mtime_age_seconds": round(mtime_age_seconds, 3),
                "parse_scope": parse_scope,
                "partial_parse": partial_parse,
            },
            sort_keys=True,
        ),
    )
    return result


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
    from internal.council.expert_attribution import normalize_expert

    return normalize_expert(prediction)


def _stamp_and_nudge_expert(
    prediction: Dict[str, Any],
    *,
    correct: bool,
    capture: Optional[CaptureResult] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Stamp rich attribution on the row; nudge the SAME attributed expert so
    attribution stamping and weight nudging stay in agreement (fixes quant
    sink / dark_horse starvation where legacy string normalization diverged).""
    from internal.council.expert_attribution import resolve_expert_attribution
    from internal.council.signal_expert import expert_for_replay_row
    from internal.learning.evidence import evidence_population, stamp_evidence

    stamped_expert, expert_source = resolve_expert_attribution(prediction)
    stamp_evidence(prediction)
    if stamped_expert:
        prediction["expert"] = stamped_expert
        if expert_source != "existing":
            prediction["expert_attribution_source"] = expert_source
    # Outcome weights require both a published council row and attributable
    # signal evidence. A bare legacy expert label is diagnostic only.
    replay_expert = expert_for_replay_row(prediction)
    nudge_expert = (
        stamped_expert
        if evidence_population(prediction) == "council_published"
        and replay_expert == stamped_expert
        else None
    )
    if nudge_expert and not _skip_council_learning(prediction):
        _nudge_weights(bool(correct), nudge_expert, capture=capture)
    return stamped_expert, nudge_expert


def _nudge_weights(
    correct: bool,
    expert: Optional[str],
    *,
    capture: Optional[CaptureResult] = None,
) -> None:
    if _in_replay_mode() or not expert:
        return

    from internal.council.weights import load_weights, nudge_expert

    nudge_correct = bool(correct)
    scale = 1.0
    extra: Dict[str, Any] = {}
    if capture_mode_enabled() and capture is not None:
        flag = capture_nudge_correct(capture)
        if flag is None:
            return
        nudge_correct = bool(flag)
        mult = nudge_multiplier(capture)
        if mult is None:
            return
        scale = float(mult)
        extra = {"band": capture.band, "capture": capture.capture_capped}

    before = float(load_weights().get(expert, 1.0))
    after = nudge_expert(expert, nudge_correct, scale=scale)
    if after is None:
        return
    try:
        from internal.learning.trail_bus import emit_weight_change

        emit_weight_change(
            expert,
            before=before,
            after=float(after),
            reason="prediction_resolve",
            correct=nudge_correct,
            extra=extra or None,
        )
    except Exception:
        pass


# Metabolism map only — not UI nesting. Leading auditor at pick-time soft-nudges
# the experts that auditor role traditionally covers.
_JUDGE_AUDIT_EXPERTS = {
    "oracle": ("quant", "technical"),
    "echo": ("dark_horse",),
    "pulse": ("hype",),
}
_JUDGE_AUDIT_DELTA_OK = 0.01
_JUDGE_AUDIT_DELTA_BAD = -0.015


def _leading_judge_name(scores_at_creation: Any) -> Optional[str]:
    if not isinstance(scores_at_creation, dict):
        return None
    best_name = None
    best_val = float("-inf")
    for name in ("oracle", "echo", "pulse"):
        block = scores_at_creation.get(name)
        raw = None
        if isinstance(block, dict):
            raw = block.get("score", block.get("confidence"))
        elif isinstance(block, (int, float)):
            raw = block
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val > best_val:
            best_val = val
            best_name = name
    return best_name


def _nudge_weights_from_judge_audit(prediction: Dict[str, Any], correct: bool) -> None:
    """Half-strength weight nudge from leading Oracle/Echo/Pulse score at creation.

    Not invoked on live resolve — stacks with primary expert nudge on the same
    experts (ponytail: one credit per outcome). Kept for tests / optional replay.
    """
    if _in_replay_mode():
        return
    leading = _leading_judge_name(prediction.get("judge_scores_at_creation"))
    if not leading:
        return
    experts = _JUDGE_AUDIT_EXPERTS.get(leading)
    if not experts:
        return
    for expert in experts:
        before = float(load_weights().get(expert, 1.0))
        after = nudge_expert(expert, correct, scale=0.5)
        if after is not None:
            nudge_signal_weight(expert, after - before, source="judge_audit")


def atomic_finalize_resolution(
    prediction: Dict[str, Any],
    resolved: List[Dict[str, Any]],
    correct: bool,
    captured: Optional[CaptureResult] = None,
) -> None:
    """Commit the resolved row atomically. Write to both resolved and predictions
    files in a single pass to avoid partial writes during concurrent loads."""
    from internal.council.capture import BANDS

    band = prediction.get("band")
    if not band or band not in BANDS:
        raise ValueError("Cannot finalize unband prediction")

    data = load_predictions(persist=False)
    preds = data.get("predictions", [])
    res = data.get("resolved", [])

    # Find matching pending row (unique key: netuid+horizon_type+shadow)
    key = lambda p: (p.get("netuid"), p.get("horizon_type", "hour"), bool(p.get("shadow") or p.get("counterfactual")))
    idx = None
    for i, p in enumerate(preds):
        if key(p) == key(prediction):
            idx = i
            break
    if idx is None:
        raise ValueError("No pending row found for resolution")

    # Swap in the resolved prediction (removes from pending)
    resolved_row = preds.pop(idx)
    resolved_row.update(prediction)
    resolved_row["status"] = "resolved"
    res.append(resolved_row)

    data["predictions"] = preds
    data["resolved"] = res
    save_predictions(data)


def resolve_all() -> Dict[str, Any]:
    """Main resolver entry point. Iterate over all pending predictions, resolve
    them against cached or live prices, and commit results atomically."""
    from internal.council.deduplication import dedupe_predictions
    from internal.learning.evidence import stamp_evidence

    data = load_predictions(persist=False)
    pending = data.get("predictions", [])
    resolved = data.get("resolved", [])

    # Dedupe pending by key (netuid+horizon_type+shadow)
    pending = dedupe_predictions(pending)
    if not pending:
        return {"resolved": 0, "expired": 0, "pending": 0}

    # Check watchdog before resolution
    check_resolver_watchdog(pending)

    # Resolve each

    resolved_count = 0
    expired_count = 0
    prices = fetch_prices()
    now = datetime.now(timezone.utc)
    for p in pending:
        try:
            # Check expiry
            resolve_at = p.get("resolve_at")
            if resolve_at:
                from datetime import datetime, timezone
                ra = datetime.fromisoformat(resolve_at.replace("Z", "+00:00"))
                if now >= ra + timedelta(hours=_EXPIRY_DEFAULT_HORIZON_HOURS * _EXPIRY_GRACE_MULTIPLE):
                    # Expired — mark as miss and archive
                    p["status"] = "miss"
                    p["correct"] = False
                    resolved.append(p)
                    expired_count += 1
                    continue

            # Get price
            uid = p.get("netuid")
            current = prices.get(uid)
            if current is None:
                # Skip resolution for now (no price available)
                continue

            # Classify
            outcome = classify_outcome(p, current)
            correct = outcome == "correct"

            # Stamp attribution and nudge
            _, _ = _stamp_and_nudge_expert(p, correct=correct)

            # Commit
            atomic_finalize_resolution(p, resolved, correct, captured=None)
            resolved_count += 1
        except Exception as e:
            logger.error("Failed to resolve prediction %s: %s", p.get("netuid"), e)
            continue

    # Update stats
    update_stats(data)
    save_predictions(data)

    return {"resolved": resolved_count, "expired": expired_count, "pending": len(pending)}
