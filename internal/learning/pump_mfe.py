"""P0.3 — Maximum favorable excursion (MFE) instrumentation for pump desk claims.

Additive measurement only. Does not change terminal ``correct``/``outcome`` grading
and never mutates frozen ``signal_snapshot`` rows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from internal.council.grading import compute_actual_pct, is_pump_desk_claim

logger = logging.getLogger(__name__)

DEFAULT_CLAIM_PCT = 2.0


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


def terminal_return_1h(reference_price: float, terminal_price: float) -> float:
    """Percent return from reference to terminal (same convention as actual_pct)."""
    return float(compute_actual_pct(float(reference_price), float(terminal_price)))


def _favorable_price(candle: Dict[str, Any], *, direction: str = "up") -> float:
    """Price used for favorable excursion on one candle."""
    direction = (direction or "up").lower()
    high = candle.get("high")
    low = candle.get("low")
    close = candle.get("close", candle.get("price"))
    try:
        if direction in {"up", "long", "bullish"} and high is not None:
            return float(high)
        if direction in {"down", "short", "bearish"} and low is not None:
            return float(low)
        return float(close or 0)
    except (TypeError, ValueError):
        try:
            return float(close or 0)
        except (TypeError, ValueError):
            return 0.0


def mfe_max_1h(
    reference_price: float,
    candles_or_prices: Sequence[Any],
    *,
    direction: str = "up",
) -> float:
    """Maximum favorable excursion vs reference within a price series.

    ``candles_or_prices`` may be candle dicts (prefer ``high`` for longs) or bare
    floats. Returns percent points (same units as ``actual_pct``). Empty/invalid
    series yields 0.0 when reference is valid (no favorable move observed).
    """
    ref = float(reference_price or 0)
    if ref <= 0:
        return 0.0
    best = 0.0
    for item in candles_or_prices or []:
        if isinstance(item, dict):
            price = _favorable_price(item, direction=direction)
        else:
            try:
                price = float(item)
            except (TypeError, ValueError):
                continue
        if price <= 0:
            continue
        if direction.lower() in {"down", "short", "bearish"}:
            excursion = (ref - price) / ref * 100.0
        else:
            excursion = (price - ref) / ref * 100.0
        if excursion > best:
            best = excursion
    return round(best, 4)


def candles_in_horizon(
    candles: Iterable[Dict[str, Any]],
    *,
    start: datetime,
    end: datetime,
) -> List[Dict[str, Any]]:
    """Candles with timestamp in ``[start, end]`` inclusive."""
    out: List[Dict[str, Any]] = []
    start_ts = start.timestamp()
    end_ts = end.timestamp()
    for candle in candles or []:
        if not isinstance(candle, dict):
            continue
        ts = _parse_ts(candle.get("timestamp"))
        if ts is None:
            continue
        t = ts.timestamp()
        if start_ts <= t <= end_ts:
            out.append(candle)
    return out


def compute_mfe_for_prediction(
    prediction: Dict[str, Any],
    *,
    terminal_price: Optional[float] = None,
    candles: Optional[Sequence[Dict[str, Any]]] = None,
    cache: Optional[Dict[str, Any]] = None,
    cache_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute MFE fields for one prediction without mutating snapshots.

    Returns a dict with keys:
      terminal_return_1h, mfe_max_1h, mfe_regradable, mfe_ungradeable_reason
    """
    result: Dict[str, Any] = {
        "terminal_return_1h": None,
        "mfe_max_1h": None,
        "mfe_regradable": False,
        "mfe_ungradeable_reason": None,
    }
    try:
        ref = float(prediction.get("reference_price") or 0)
    except (TypeError, ValueError):
        ref = 0.0
    if ref <= 0:
        result["mfe_ungradeable_reason"] = "bad_reference_price"
        return result

    price = terminal_price
    if price is None:
        try:
            price = float(prediction.get("resolved_price") or 0) or None
        except (TypeError, ValueError):
            price = None
    if price is not None and float(price) > 0:
        result["terminal_return_1h"] = terminal_return_1h(ref, float(price))

    window = list(candles) if candles is not None else None
    if window is None:
        created = _parse_ts(prediction.get("created_at"))
        resolve_at = _parse_ts(prediction.get("resolve_at") or prediction.get("resolved_at"))
        if created is None or resolve_at is None:
            result["mfe_ungradeable_reason"] = "missing_horizon_bounds"
            # terminal may still be set
            if result["terminal_return_1h"] is not None:
                # terminal alone is not full MFE regrade
                pass
            return result
        try:
            from internal.council.price_reference import PRICE_CACHE_PATH, _candles_for_netuid
            from internal.file_utils import safe_read_json

            path = cache_path or PRICE_CACHE_PATH
            disk = cache if isinstance(cache, dict) else safe_read_json(path, default={})
            if not isinstance(disk, dict):
                disk = {}
            raw = _candles_for_netuid(disk, prediction.get("netuid"))
            window = candles_in_horizon(raw, start=created, end=resolve_at)
        except Exception as exc:
            logger.debug("pump_mfe candle load failed: %s", exc)
            result["mfe_ungradeable_reason"] = "candle_load_failed"
            return result

    if not window:
        result["mfe_ungradeable_reason"] = "missing_horizon_candles"
        return result

    direction = str(prediction.get("direction") or "up")
    result["mfe_max_1h"] = mfe_max_1h(ref, window, direction=direction)
    result["mfe_regradable"] = True
    result["mfe_ungradeable_reason"] = None
    return result


def stamp_pump_mfe_fields(
    prediction: Dict[str, Any],
    *,
    terminal_price: Optional[float] = None,
    candles: Optional[Sequence[Dict[str, Any]]] = None,
    cache: Optional[Dict[str, Any]] = None,
    cache_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Additively stamp MFE fields on ``prediction``. Never touches signal_snapshot."""
    if not isinstance(prediction, dict) or not is_pump_desk_claim(prediction):
        return prediction
    snap_before = prediction.get("signal_snapshot")
    fields = compute_mfe_for_prediction(
        prediction,
        terminal_price=terminal_price,
        candles=candles,
        cache=cache,
        cache_path=cache_path,
    )
    prediction["terminal_return_1h"] = fields["terminal_return_1h"]
    prediction["mfe_max_1h"] = fields["mfe_max_1h"]
    prediction["mfe_regradable"] = bool(fields["mfe_regradable"])
    if fields["mfe_ungradeable_reason"]:
        prediction["mfe_ungradeable_reason"] = fields["mfe_ungradeable_reason"]
    else:
        prediction.pop("mfe_ungradeable_reason", None)
    # Frozen snapshot must remain identical object / content.
    if snap_before is not prediction.get("signal_snapshot"):
        prediction["signal_snapshot"] = snap_before
    return prediction


def mfe_hit(prediction: Dict[str, Any], *, claim_pct: Optional[float] = None) -> Optional[bool]:
    """True when mfe_max_1h meets the claim threshold; None if not regradable."""
    if prediction.get("mfe_max_1h") is None or not prediction.get("mfe_regradable"):
        return None
    try:
        threshold = float(
            claim_pct
            if claim_pct is not None
            else (prediction.get("predicted_pct") or DEFAULT_CLAIM_PCT)
        )
    except (TypeError, ValueError):
        threshold = DEFAULT_CLAIM_PCT
    try:
        return float(prediction["mfe_max_1h"]) >= threshold
    except (TypeError, ValueError):
        return None


def backfill_pump_mfe(
    data: Dict[str, Any],
    *,
    cache: Optional[Dict[str, Any]] = None,
    cache_path: Optional[str] = None,
    dry_run: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Recompute MFE fields on historical pump desk rows. Returns (data, summary)."""
    from internal.council.price_reference import PRICE_CACHE_PATH
    from internal.file_utils import safe_read_json

    path = cache_path or PRICE_CACHE_PATH
    disk = cache if isinstance(cache, dict) else safe_read_json(path, default={})
    if not isinstance(disk, dict):
        disk = {}

    summary: Dict[str, Any] = {
        "dry_run": dry_run,
        "scanned": 0,
        "regradable": 0,
        "not_regradable": 0,
        "skipped_non_pump": 0,
        "reasons": {},
    }

    out = data if not dry_run else {
        "predictions": list(data.get("predictions") or []),
        "resolved": [dict(r) if isinstance(r, dict) else r for r in (data.get("resolved") or [])],
    }
    # Always work on copies of resolved rows when dry_run; when writing, mutate in place.
    resolved = out.setdefault("resolved", [])
    if not isinstance(resolved, list):
        resolved = []
        out["resolved"] = resolved

    working = resolved if not dry_run else resolved

    for idx, row in enumerate(list(working)):
        if not isinstance(row, dict):
            continue
        if not is_pump_desk_claim(row):
            summary["skipped_non_pump"] += 1
            continue
        summary["scanned"] += 1
        snap_before = row.get("signal_snapshot")
        # Use a copy when dry_run so callers can inspect without mutating input.
        target = row if not dry_run else dict(row)
        stamp_pump_mfe_fields(target, cache=disk, cache_path=path)
        if target.get("signal_snapshot") is not snap_before and snap_before is not None:
            # Ensure snapshot identity/content preserved
            target["signal_snapshot"] = snap_before
        if dry_run:
            working[idx] = target
        if target.get("mfe_regradable"):
            summary["regradable"] += 1
        else:
            summary["not_regradable"] += 1
            reason = str(target.get("mfe_ungradeable_reason") or "unknown")
            summary["reasons"][reason] = int(summary["reasons"].get(reason) or 0) + 1

    return out, summary


def report_mfe_hit_rates(data: Dict[str, Any]) -> Dict[str, Any]:
    """Per-grading-type hit rates: terminal-only vs MFE, side by side."""
    from internal.learning.pump_lead_stats import _gradeable_pump_rows, _is_early_claim

    rows = _gradeable_pump_rows(data.get("resolved") or [])
    early = [r for r in rows if _is_early_claim(r)]
    just = [r for r in rows if not _is_early_claim(r)]

    def _bucket(bucket: List[Dict[str, Any]]) -> Dict[str, Any]:
        terminal_hits = sum(1 for r in bucket if r.get("correct") is True)
        terminal_n = len(bucket)
        terminal_rate = round(terminal_hits / terminal_n, 4) if terminal_n else None

        mfe_rows = [r for r in bucket if r.get("mfe_regradable") and r.get("mfe_max_1h") is not None]
        mfe_hits = sum(1 for r in mfe_rows if mfe_hit(r) is True)
        mfe_n = len(mfe_rows)
        mfe_rate = round(mfe_hits / mfe_n, 4) if mfe_n else None

        return {
            "terminal_only": {
                "n": terminal_n,
                "hits": terminal_hits,
                "hit_rate": terminal_rate,
            },
            "mfe": {
                "n": mfe_n,
                "hits": mfe_hits,
                "hit_rate": mfe_rate,
            },
        }

    return {
        "source": "predictions.json pick_source=pump_lead (+ pump desk)",
        "claim": "+2% within 1h",
        "early_pump": _bucket(early),
        "just_started": _bucket(just),
        "all": _bucket(rows),
    }
