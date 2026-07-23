"""Recover overdue pump_lead claims with correct horizon-candle grading.

Quality-first: junk samples become ungradeable (not training fuel).
Never grades with late live prices hours after resolve_at — that would
falsify the +2%/1h claim. Candle VWAP/median at resolve_at only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from internal.council.grading import (
    compute_actual_pct,
    grade_prediction,
    is_pump_lead,
)
from internal.council.price_reference import price_at_resolve_at
from internal.file_utils import safe_read_json, safe_write_json

logger = logging.getLogger(__name__)

PREDICTIONS_PATH = "data/predictions.json"
# Root / invalid netuids never become Upgrade-6 samples.
_SKIP_NETUIDS = frozenset({0})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def sample_quality_ok(prediction: Dict[str, Any]) -> Tuple[bool, str]:
    """Return (ok, reason). Best samples only for hit/miss grades."""
    try:
        nu = int(prediction.get("netuid"))
    except (TypeError, ValueError):
        return False, "bad_netuid"
    if nu in _SKIP_NETUIDS or nu < 1:
        return False, "skip_root_or_invalid"

    try:
        ref = float(prediction.get("reference_price") or 0)
    except (TypeError, ValueError):
        ref = 0.0
    if ref <= 0:
        return False, "bad_reference_price"

    phase = str(prediction.get("pump_phase") or "").upper()
    badge = str(prediction.get("pump_badge") or "").upper()
    claim = str(prediction.get("pump_claim") or "").upper()
    snap = prediction.get("signal_snapshot") if isinstance(prediction.get("signal_snapshot"), dict) else {}

    try:
        buy_ratio = float(snap.get("buy_ratio", 0.5))
    except (TypeError, ValueError):
        buy_ratio = 0.5
    try:
        vol = float(snap.get("volume_intensity", 0.0))
    except (TypeError, ValueError):
        vol = 0.0

    triad_strength = str(snap.get("triad_strength") or "").upper()
    lit = 0
    if isinstance(snap.get("triad"), dict):
        t = snap["triad"]
        lit = sum(
            1
            for k in ("inflow_quiet_load", "buy_pressure", "price_coil")
            if t.get(k)
        )
    elif snap.get("triad_lit_count") is not None:
        try:
            lit = int(snap.get("triad_lit_count") or 0)
        except (TypeError, ValueError):
            lit = 0

    # Placeholder flow (common when buy/sell missing) — weak sample unless strong triad.
    placeholder_flow = abs(buy_ratio - 0.5) < 1e-6 and (vol <= 0.01 or vol >= 0.99)

    is_building = (
        phase == "ACCUMULATING"
        or badge == "BUILDING"
        or claim in {"ACCUMULATING", "BUILDING"}
    )
    is_just = claim in {"JUST_STARTED", "JUST STARTED"} or badge == "JUST STARTED"
    strong_triad = lit >= 2 or triad_strength in {"BUILDING", "STRONG"}

    if is_building or is_just:
        if placeholder_flow and not strong_triad:
            return False, "placeholder_flow_on_building"
        return True, "ok"

    # STIRRING / WARMING UP — need non-placeholder flow or triad confirmation
    if phase == "STIRRING" or badge == "WARMING UP":
        if placeholder_flow and not strong_triad:
            return False, "weak_stirring_placeholder"
        if abs(buy_ratio - 0.5) < 1e-6 and vol < 0.12 and not strong_triad:
            return False, "weak_stirring_no_flow"
        return True, "ok"

    return False, "phase_not_lead_quality"


def _mark_ungradeable(prediction: Dict[str, Any], *, reason: str, now: datetime) -> Dict[str, Any]:
    out = dict(prediction)
    out["status"] = "ungradeable"
    out["outcome"] = "ungradeable"
    out["correct"] = None
    out["actual_pct"] = None
    out["resolved_price"] = None
    out["resolved_at"] = now.isoformat().replace("+00:00", "Z")
    out["ungradeable_reason"] = reason
    out["sample_quality"] = "reject"
    return out


def _finalize_grade(
    prediction: Dict[str, Any],
    *,
    price: float,
    meta: Dict[str, Any],
    resolve_at: datetime,
) -> Dict[str, Any]:
    ref = float(prediction.get("reference_price") or 0)
    actual_pct = compute_actual_pct(ref, price)
    correct, outcome = grade_prediction(prediction, actual_pct)
    out = dict(prediction)
    out["status"] = "resolved"
    out["outcome"] = outcome
    out["correct"] = bool(correct)
    out["actual_pct"] = actual_pct
    out["resolved_price"] = price
    out["resolved_at"] = resolve_at.isoformat().replace("+00:00", "Z")
    out["price_source"] = meta.get("price_source")
    out["price_lag_seconds"] = meta.get("price_lag_seconds")
    out["candles_in_window"] = meta.get("candles_in_window")
    out["sample_quality"] = "high"
    out["graded_via"] = "pump_lead_candle_recover"
    return out


def grade_pump_lead_at_resolve_candle(
    prediction: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
    cache: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Grade one pump_lead using candles at resolve_at only (no live fallback)."""
    now = now or _utcnow()
    if not is_pump_lead(prediction):
        return _mark_ungradeable(prediction, reason="not_pump_lead", now=now)

    ok, reason = sample_quality_ok(prediction)
    if not ok:
        return _mark_ungradeable(prediction, reason=reason, now=now)

    resolve_at = _parse_ts(prediction.get("resolve_at"))
    if resolve_at is None:
        return _mark_ungradeable(prediction, reason="missing_resolve_at", now=now)
    if now < resolve_at:
        out = dict(prediction)
        out["status"] = "pending"
        return out

    status, price, meta = price_at_resolve_at(
        prediction.get("netuid"),
        resolve_at,
        cache=cache,
    )
    if status != "ok" or price <= 0:
        # Honest empty — do not invent a late live price.
        return _mark_ungradeable(prediction, reason="missing_horizon_candles", now=now)

    return _finalize_grade(prediction, price=price, meta=meta, resolve_at=resolve_at)


def recover_overdue_pump_leads(
    *,
    path: Optional[str] = None,
    dry_run: bool = False,
    only_due: bool = True,
) -> Dict[str, Any]:
    """Move overdue pending pump_lead → resolved/ungradeable with candle grades."""
    resolved_path = path or PREDICTIONS_PATH
    data = safe_read_json(resolved_path, default={})
    if not isinstance(data, dict):
        data = {}
    pending: List[Dict[str, Any]] = list(data.get("predictions") or [])
    resolved: List[Dict[str, Any]] = list(data.get("resolved") or [])
    now = _utcnow()

    still: List[Dict[str, Any]] = []
    graded: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    kept_pending = 0

    from internal.council.price_reference import PRICE_CACHE_PATH, _load_cache

    cache = _load_cache(PRICE_CACHE_PATH)

    for pred in pending:
        if not isinstance(pred, dict) or not is_pump_lead(pred):
            still.append(pred)
            continue
        resolve_at = _parse_ts(pred.get("resolve_at"))
        if only_due and resolve_at is not None and now < resolve_at:
            still.append(pred)
            kept_pending += 1
            continue

        result = grade_pump_lead_at_resolve_candle(pred, now=now, cache=cache)
        status = result.get("status")
        if status == "pending":
            still.append(result)
            kept_pending += 1
        elif status == "resolved":
            graded.append(result)
            resolved.append(result)
        else:
            rejected.append(result)
            resolved.append(result)

    summary = {
        "ok": True,
        "dry_run": dry_run,
        "graded": len(graded),
        "rejected_ungradeable": len(rejected),
        "still_pending": sum(1 for p in still if isinstance(p, dict) and is_pump_lead(p)),
        "hits": sum(1 for r in graded if r.get("correct") is True),
        "misses": sum(1 for r in graded if r.get("correct") is False),
        "reject_reasons": {},
        "graded_netuids": [r.get("netuid") for r in graded],
    }
    for r in rejected:
        reason = str(r.get("ungradeable_reason") or "unknown")
        summary["reject_reasons"][reason] = summary["reject_reasons"].get(reason, 0) + 1

    if dry_run:
        return summary

    data["predictions"] = still
    data["resolved"] = resolved
    # Keep existing stats helper shape light — full stats recomputed by resolver.
    try:
        from internal.council.resolver import _compute_stats

        data["stats"] = _compute_stats(data)
    except Exception:
        pass
    safe_write_json(resolved_path, data)
    logger.info(
        "pump_lead recover graded=%s rejected=%s hits=%s misses=%s",
        summary["graded"],
        summary["rejected_ungradeable"],
        summary["hits"],
        summary["misses"],
    )
    try:
        from internal.learning.pump_calibration import maybe_adapt_after_resolve

        if summary["graded"]:
            maybe_adapt_after_resolve()
    except Exception:
        pass
    return summary
