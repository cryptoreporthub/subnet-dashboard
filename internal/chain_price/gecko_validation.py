"""Gecko vs chain reserve validation protocol (#1395 Fix 5 / Step 4 gate).

Pure evaluation logic: matched-hour floor, minimum qualifying subnets, and
design thresholds from finney Step 1 (median / p95 relative diff, mean return corr).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Sequence

from internal.council.grading import is_price_unit_mismatch

Verdict = Literal["PASS", "FAIL", "INCONCLUSIVE"]

DEFAULT_MIN_MATCHED_HOURS = 24
DEFAULT_MIN_QUALIFYING_SUBNETS = 8
DEFAULT_MEDIAN_REL_DIFF_MAX = 0.01
DEFAULT_P95_REL_DIFF_MAX = 0.03
DEFAULT_MEAN_HOURLY_RETURN_CORR_MIN = 0.9
# Report-only WARN threshold (#1395 comment 6215696142); does not affect PASS/FAIL.
DEFAULT_PER_SUBNET_HOURLY_LOG_RETURN_CORR_WARN_MIN = 0.7
ALIGNED_HOUR_SECONDS = 3600
# ponytail: relative tolerance for same-hour duplicate rows; upgrade path = config threshold.
_DUPLICATE_HOUR_PRICE_AGREE_REL_EPS = 1e-9


@dataclass(frozen=True)
class ValidationThresholds:
    median_rel_diff_max: float = DEFAULT_MEDIAN_REL_DIFF_MAX
    p95_rel_diff_max: float = DEFAULT_P95_REL_DIFF_MAX
    mean_hourly_return_corr_min: float = DEFAULT_MEAN_HOURLY_RETURN_CORR_MIN
    per_subnet_hourly_log_return_corr_warn_min: float = (
        DEFAULT_PER_SUBNET_HOURLY_LOG_RETURN_CORR_WARN_MIN
    )


@dataclass
class MatchedHour:
    gecko_close: float
    chain_price_tao: float
    hour_unix: Optional[int] = None


@dataclass
class SubnetValidationInput:
    netuid: int
    pool: str = ""
    matched: List[MatchedHour] = field(default_factory=list)
    error: Optional[str] = None


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den_x = sum((a - mx) ** 2 for a in xs)
    den_y = sum((b - my) ** 2 for b in ys)
    den = math.sqrt(den_x * den_y)
    if den == 0:
        return None
    return num / den


def _matched_hour_prices_agree(a: MatchedHour, b: MatchedHour) -> bool:
    for v1, v2 in ((a.gecko_close, b.gecko_close), (a.chain_price_tao, b.chain_price_tao)):
        if not (math.isfinite(v1) and math.isfinite(v2)):
            return False
        scale = max(abs(v1), abs(v2), 1e-30)
        if abs(v1 - v2) / scale > _DUPLICATE_HOUR_PRICE_AGREE_REL_EPS:
            return False
    return True


def _prepare_matched_hours(
    matched: Sequence[MatchedHour],
) -> tuple[List[MatchedHour], int, Optional[str]]:
    """Order rows for metrics: all stamped → sort/dedupe; all unstamped → input order."""
    stamped = [(i, row) for i, row in enumerate(matched) if row.hour_unix is not None]
    unstamped = [(i, row) for i, row in enumerate(matched) if row.hour_unix is None]
    if stamped and unstamped:
        return [], 0, "mixed_hour_unix"
    if not stamped:
        return [row for _, row in sorted(unstamped, key=lambda t: t[0])], 0, None
    stamped.sort(key=lambda t: (int(t[1].hour_unix), t[0]))
    by_ts: Dict[int, MatchedHour] = {}
    dup_dropped = 0
    for _, row in stamped:
        ts = int(row.hour_unix)
        if ts in by_ts:
            dup_dropped += 1
            if not _matched_hour_prices_agree(by_ts[ts], row):
                return [], dup_dropped, "conflicting_duplicate_hour_unix"
        by_ts[ts] = row
    ordered = [by_ts[ts] for ts in sorted(by_ts)]
    return ordered, dup_dropped, None


def _hourly_log_returns_scaled(
    closes: Sequence[float], hour_unix: Sequence[int]
) -> List[float]:
    """Hourly log returns with elapsed-time scaling (#1395 gap fix).

    Each consecutive pair uses dt = hour_unix[i] - hour_unix[i-1]. The raw log move
    log(close[i]/close[i-1]) is multiplied by (ALIGNED_HOUR_SECONDS / dt) so a move
    over 7200s counts as half the per-hour rate. When dt is exactly 3600s this
    matches naive adjacent-hour pairing.
    """
    if len(closes) != len(hour_unix):
        return []
    out: List[float] = []
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        dt = int(hour_unix[i]) - int(hour_unix[i - 1])
        if dt <= 0:
            continue
        if not (math.isfinite(prev) and math.isfinite(cur)) or prev <= 0 or cur <= 0:
            continue
        out.append(math.log(cur / prev) * (ALIGNED_HOUR_SECONDS / dt))
    return out


def subnet_metrics(matched: Sequence[MatchedHour]) -> Dict[str, Any]:
    """Per-subnet stats from aligned Gecko close vs chain reserve price."""
    ordered, duplicate_hour_unix_dropped, integrity_error = _prepare_matched_hours(matched)
    if integrity_error:
        return {
            "matched_hours": 0,
            "n_return_pairs": 0,
            "return_pair_gap_skips": 0,
            "duplicate_hour_unix_dropped": duplicate_hour_unix_dropped,
            "rel_diffs": [],
            "hourly_log_return_corr": None,
            "data_integrity_error": integrity_error,
        }
    rel_diffs: List[float] = []
    gecko_closes: List[float] = []
    chain_closes: List[float] = []
    hour_unix: List[int] = []
    all_unstamped = ordered and ordered[0].hour_unix is None
    synthetic = 0
    for row in ordered:
        g, c = row.gecko_close, row.chain_price_tao
        if not (math.isfinite(g) and math.isfinite(c)) or g <= 0 or c <= 0:
            continue
        rel_diffs.append(abs(c - g) / g)
        gecko_closes.append(g)
        chain_closes.append(c)
        if all_unstamped:
            hour_unix.append(synthetic)
            synthetic += ALIGNED_HOUR_SECONDS
        else:
            hour_unix.append(int(row.hour_unix))
    adjacent_pairs = max(0, len(gecko_closes) - 1)
    rets_g = _hourly_log_returns_scaled(gecko_closes, hour_unix)
    rets_c = _hourly_log_returns_scaled(chain_closes, hour_unix)
    n_return_pairs = min(len(rets_g), len(rets_c))
    return_pair_gap_skips = adjacent_pairs - n_return_pairs
    corr = (
        _pearson(rets_g[:n_return_pairs], rets_c[:n_return_pairs])
        if n_return_pairs >= 3
        else None
    )
    return {
        "matched_hours": len(rel_diffs),
        "n_return_pairs": n_return_pairs,
        "return_pair_gap_skips": return_pair_gap_skips,
        "duplicate_hour_unix_dropped": duplicate_hour_unix_dropped,
        "rel_diffs": rel_diffs,
        "hourly_log_return_corr": corr,
        "data_integrity_error": None,
    }


def subnet_unit_mismatch(matched: Sequence[MatchedHour]) -> bool:
    """True if any aligned hour fails the council price-unit guard."""
    for row in matched:
        g, c = row.gecko_close, row.chain_price_tao
        if not (math.isfinite(g) and math.isfinite(c)):
            continue
        if is_price_unit_mismatch(g, c):
            return True
    return False


def _p95(values: Sequence[float]) -> Optional[float]:
    """Nearest-rank 95th percentile (NIST R-8 style, 1-based rank).

    For n sorted values, p95 is the value at rank ceil(0.95 * n), i.e. index
    ceil(0.95 * n) - 1. Using int(0.95 * n) - 1 is one rank too low when 0.95*n
    is not an integer (e.g. n=192 → rank 183, not 182).
    """
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    idx = max(0, math.ceil(0.95 * n) - 1)
    return ordered[idx]


def evaluate_gecko_validation(
    subnets: Sequence[SubnetValidationInput],
    *,
    min_matched_hours: int = DEFAULT_MIN_MATCHED_HOURS,
    min_qualifying_subnets: int = DEFAULT_MIN_QUALIFYING_SUBNETS,
    thresholds: ValidationThresholds | None = None,
) -> Dict[str, Any]:
    """Return a report dict including verdict PASS / FAIL / INCONCLUSIVE."""
    th = thresholds or ValidationThresholds()
    per_subnet_out: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    failing_subnets: List[Dict[str, Any]] = []
    unit_mismatch_below_floor: List[Dict[str, Any]] = []
    qualifying_rel: List[float] = []
    qualifying_corrs: List[float] = []
    qualifying_count = 0
    warnings: List[Dict[str, Any]] = []

    for sub in subnets:
        row: Dict[str, Any] = {"netuid": sub.netuid, "pool": sub.pool}
        if sub.error:
            row["error"] = sub.error
            row["matched_hours"] = 0
            per_subnet_out.append(row)
            excluded.append({"netuid": sub.netuid, "matched_hours": 0, "reason": sub.error})
            continue
        metrics = subnet_metrics(sub.matched)
        integrity_error = metrics.get("data_integrity_error")
        if integrity_error:
            unit_bad = False
        else:
            ordered_for_unit, _, _ = _prepare_matched_hours(sub.matched)
            unit_bad = subnet_unit_mismatch(ordered_for_unit)
        median_rd = statistics.median(metrics["rel_diffs"]) if metrics["rel_diffs"] else None
        corr = metrics["hourly_log_return_corr"]
        mh = metrics["matched_hours"]
        n_return_pairs = metrics["n_return_pairs"]
        min_return_pairs = min_matched_hours - 1
        meets_hour_floor = mh >= min_matched_hours
        meets_return_pair_floor = n_return_pairs >= min_return_pairs
        at_floor = meets_hour_floor and meets_return_pair_floor
        corr_warn = (
            at_floor
            and corr is not None
            and corr < th.per_subnet_hourly_log_return_corr_warn_min
        )
        row.update(
            {
                "matched_hours": mh,
                "n_return_pairs": n_return_pairs,
                "return_pair_gap_skips": metrics["return_pair_gap_skips"],
                "duplicate_hour_unix_dropped": metrics["duplicate_hour_unix_dropped"],
                "data_integrity_error": integrity_error,
                "median_rel_diff": median_rd,
                "p95_rel_diff": _p95(metrics["rel_diffs"]),
                "hourly_log_return_corr": corr,
                "corr_below_warn_threshold": corr_warn,
                "price_unit_mismatch": unit_bad,
            }
        )
        if integrity_error:
            per_subnet_out.append(row)
            raw_matched_hours = len(sub.matched)
            excluded.append(
                {
                    "netuid": sub.netuid,
                    "matched_hours": raw_matched_hours,
                    "n_return_pairs": n_return_pairs,
                    "reason": integrity_error,
                }
            )
            failing_subnets.append(
                {
                    "netuid": sub.netuid,
                    "reasons": [f"data_integrity_error:{integrity_error}"],
                }
            )
            continue
        if corr_warn:
            warnings.append(
                {
                    "netuid": sub.netuid,
                    "kind": "hourly_log_return_corr_below_warn",
                    "hourly_log_return_corr": corr,
                    "warn_min": th.per_subnet_hourly_log_return_corr_warn_min,
                }
            )
        per_subnet_out.append(row)
        if not meets_hour_floor:
            if unit_bad:
                unit_mismatch_below_floor.append(
                    {"netuid": sub.netuid, "matched_hours": mh}
                )
            excluded.append(
                {
                    "netuid": sub.netuid,
                    "matched_hours": mh,
                    "n_return_pairs": n_return_pairs,
                    "reason": f"below_floor_{min_matched_hours}h",
                }
            )
            continue
        if not meets_return_pair_floor:
            excluded.append(
                {
                    "netuid": sub.netuid,
                    "matched_hours": mh,
                    "n_return_pairs": n_return_pairs,
                    "reason": "insufficient_return_pairs",
                }
            )
            continue
        fail_reasons: List[str] = []
        if unit_bad:
            fail_reasons.append("price_unit_mismatch")
        if median_rd is not None and median_rd > th.median_rel_diff_max:
            fail_reasons.append("median_rel_diff_exceeds_max")
        if corr is None:
            # Correlation is undefined (flat series), so the subnet cannot count toward
            # the quorum, but a price disagreement seen at or above the floor still fails.
            excluded.append(
                {
                    "netuid": sub.netuid,
                    "matched_hours": mh,
                    "reason": "undefined_return_corr",
                }
            )
            if fail_reasons:
                failing_subnets.append({"netuid": sub.netuid, "reasons": fail_reasons})
            continue
        if fail_reasons:
            failing_subnets.append({"netuid": sub.netuid, "reasons": fail_reasons})
            continue
        qualifying_count += 1
        qualifying_rel.extend(metrics["rel_diffs"])
        qualifying_corrs.append(corr)

    aggregate: Dict[str, Any] = {
        "qualifying_subnet_count": qualifying_count,
        "excluded_subnet_count": len(excluded),
        "n_price_points": len(qualifying_rel),
        "subnets_with_corr": len(qualifying_corrs),
    }
    threshold_checks: Dict[str, Any] = {}
    if qualifying_rel:
        aggregate["median_rel_diff"] = statistics.median(qualifying_rel)
        aggregate["p95_rel_diff"] = _p95(qualifying_rel)
        threshold_checks["median_rel_diff_le_max"] = (
            aggregate["median_rel_diff"] <= th.median_rel_diff_max
        )
        threshold_checks["p95_rel_diff_le_max"] = aggregate["p95_rel_diff"] <= th.p95_rel_diff_max
    if qualifying_corrs:
        aggregate["mean_hourly_log_return_corr"] = statistics.mean(qualifying_corrs)
        threshold_checks["mean_hourly_log_return_corr_ge_min"] = (
            aggregate["mean_hourly_log_return_corr"] >= th.mean_hourly_return_corr_min
        )

    threshold_checks["per_subnet_median_and_unit"] = len(failing_subnets) == 0

    at_floor_unit_mismatch = any(
        "price_unit_mismatch" in row.get("reasons", []) for row in failing_subnets
    )
    floor_evaluated = qualifying_count + len(failing_subnets)
    if at_floor_unit_mismatch:
        verdict: Verdict = "FAIL"
    elif failing_subnets and floor_evaluated >= min_qualifying_subnets:
        # A definite failure on enough evaluated subnets must not be downgraded by a
        # below-floor warning.
        verdict = "FAIL"
    elif unit_mismatch_below_floor:
        verdict = "INCONCLUSIVE"
    elif qualifying_count < min_qualifying_subnets:
        verdict = "INCONCLUSIVE"
    elif not qualifying_rel or not qualifying_corrs:
        verdict = "INCONCLUSIVE"
    elif failing_subnets or not all(threshold_checks.values()):
        verdict = "FAIL"
    else:
        verdict = "PASS"

    return {
        "verdict": verdict,
        "parameters": {
            "min_matched_hours_per_subnet": min_matched_hours,
            "min_qualifying_subnets": min_qualifying_subnets,
            "thresholds": {
                "median_rel_diff_max": th.median_rel_diff_max,
                "p95_rel_diff_max": th.p95_rel_diff_max,
                "mean_hourly_log_return_corr_min": th.mean_hourly_return_corr_min,
                "per_subnet_hourly_log_return_corr_warn_min": (
                    th.per_subnet_hourly_log_return_corr_warn_min
                ),
            },
        },
        "aggregate": aggregate,
        "threshold_checks": threshold_checks,
        "warnings": warnings,
        "excluded_subnets": excluded,
        "failing_subnets": failing_subnets,
        "unit_mismatch_below_floor": unit_mismatch_below_floor,
        "per_subnet": per_subnet_out,
    }


def subnets_from_serializable(rows: Sequence[Dict[str, Any]]) -> List[SubnetValidationInput]:
    """Load subnet inputs from JSON-friendly dicts (script / fixtures)."""
    out: List[SubnetValidationInput] = []
    for row in rows:
        matched: List[MatchedHour] = []
        for pt in row.get("matched_hours_data") or row.get("matched") or []:
            if isinstance(pt, dict):
                ts = pt.get("hour_unix")
                if ts is None:
                    ts = pt.get("ts_unix") or pt.get("timestamp")
                matched.append(
                    MatchedHour(
                        gecko_close=float(pt["gecko_close"]),
                        chain_price_tao=float(pt["chain_price_tao"]),
                        hour_unix=int(ts) if ts is not None else None,
                    )
                )
            elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                hour_u = int(pt[2]) if len(pt) >= 3 else None
                matched.append(
                    MatchedHour(
                        gecko_close=float(pt[0]),
                        chain_price_tao=float(pt[1]),
                        hour_unix=hour_u,
                    )
                )
        out.append(
            SubnetValidationInput(
                netuid=int(row["netuid"]),
                pool=str(row.get("pool") or ""),
                matched=matched,
                error=row.get("error"),
            )
        )
    return out
