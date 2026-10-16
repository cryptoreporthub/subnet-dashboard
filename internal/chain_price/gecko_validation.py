"""Gecko vs chain reserve validation protocol (#1395 Fix 5 / Step 4 gate).

Pure evaluation logic: matched-hour floor, minimum qualifying subnets, and
design thresholds from finney Step 1 (median / p95 relative diff, mean return corr).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

Verdict = Literal["PASS", "FAIL", "INCONCLUSIVE"]

DEFAULT_MIN_MATCHED_HOURS = 24
DEFAULT_MIN_QUALIFYING_SUBNETS = 8
DEFAULT_MEDIAN_REL_DIFF_MAX = 0.01
DEFAULT_P95_REL_DIFF_MAX = 0.03
DEFAULT_MEAN_HOURLY_RETURN_CORR_MIN = 0.9


@dataclass(frozen=True)
class ValidationThresholds:
    median_rel_diff_max: float = DEFAULT_MEDIAN_REL_DIFF_MAX
    p95_rel_diff_max: float = DEFAULT_P95_REL_DIFF_MAX
    mean_hourly_return_corr_min: float = DEFAULT_MEAN_HOURLY_RETURN_CORR_MIN


@dataclass
class MatchedHour:
    gecko_close: float
    chain_price_tao: float


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


def _hourly_log_returns(closes: Sequence[float]) -> List[float]:
    out: List[float] = []
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        if prev <= 0 or cur <= 0:
            continue
        out.append(math.log(cur / prev))
    return out


def subnet_metrics(matched: Sequence[MatchedHour]) -> Dict[str, Any]:
    """Per-subnet stats from aligned Gecko close vs chain reserve price."""
    rel_diffs: List[float] = []
    gecko_closes: List[float] = []
    chain_closes: List[float] = []
    for row in matched:
        g, c = row.gecko_close, row.chain_price_tao
        if g <= 0 or c <= 0:
            continue
        rel_diffs.append(abs(c - g) / g)
        gecko_closes.append(g)
        chain_closes.append(c)
    rets_g = _hourly_log_returns(gecko_closes)
    rets_c = _hourly_log_returns(chain_closes)
    n = min(len(rets_g), len(rets_c))
    corr = _pearson(rets_g[:n], rets_c[:n]) if n >= 3 else None
    return {
        "matched_hours": len(rel_diffs),
        "rel_diffs": rel_diffs,
        "hourly_log_return_corr": corr,
    }


def _p95(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, int(0.95 * len(ordered)) - 1)
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
    qualifying_rel: List[float] = []
    qualifying_corrs: List[float] = []

    for sub in subnets:
        row: Dict[str, Any] = {"netuid": sub.netuid, "pool": sub.pool}
        if sub.error:
            row["error"] = sub.error
            row["matched_hours"] = 0
            per_subnet_out.append(row)
            excluded.append({"netuid": sub.netuid, "matched_hours": 0, "reason": sub.error})
            continue
        metrics = subnet_metrics(sub.matched)
        row.update(
            {
                "matched_hours": metrics["matched_hours"],
                "median_rel_diff": (
                    statistics.median(metrics["rel_diffs"]) if metrics["rel_diffs"] else None
                ),
                "p95_rel_diff": _p95(metrics["rel_diffs"]),
                "hourly_log_return_corr": metrics["hourly_log_return_corr"],
            }
        )
        per_subnet_out.append(row)
        mh = metrics["matched_hours"]
        if mh < min_matched_hours:
            excluded.append(
                {
                    "netuid": sub.netuid,
                    "matched_hours": mh,
                    "reason": f"below_floor_{min_matched_hours}h",
                }
            )
            continue
        qualifying_rel.extend(metrics["rel_diffs"])
        corr = metrics["hourly_log_return_corr"]
        if corr is not None:
            qualifying_corrs.append(corr)

    qualifying_count = sum(
        1
        for s in per_subnet_out
        if not s.get("error") and int(s.get("matched_hours") or 0) >= min_matched_hours
    )

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

    if qualifying_count < min_qualifying_subnets:
        verdict: Verdict = "INCONCLUSIVE"
    elif not qualifying_rel or not qualifying_corrs:
        verdict = "INCONCLUSIVE"
    elif all(threshold_checks.values()):
        verdict = "PASS"
    else:
        verdict = "FAIL"

    return {
        "verdict": verdict,
        "parameters": {
            "min_matched_hours_per_subnet": min_matched_hours,
            "min_qualifying_subnets": min_qualifying_subnets,
            "thresholds": {
                "median_rel_diff_max": th.median_rel_diff_max,
                "p95_rel_diff_max": th.p95_rel_diff_max,
                "mean_hourly_log_return_corr_min": th.mean_hourly_return_corr_min,
            },
        },
        "aggregate": aggregate,
        "threshold_checks": threshold_checks,
        "excluded_subnets": excluded,
        "per_subnet": per_subnet_out,
    }


def subnets_from_serializable(rows: Sequence[Dict[str, Any]]) -> List[SubnetValidationInput]:
    """Load subnet inputs from JSON-friendly dicts (script / fixtures)."""
    out: List[SubnetValidationInput] = []
    for row in rows:
        matched: List[MatchedHour] = []
        for pt in row.get("matched_hours_data") or row.get("matched") or []:
            if isinstance(pt, dict):
                matched.append(
                    MatchedHour(
                        gecko_close=float(pt["gecko_close"]),
                        chain_price_tao=float(pt["chain_price_tao"]),
                    )
                )
            elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                matched.append(MatchedHour(gecko_close=float(pt[0]), chain_price_tao=float(pt[1])))
        out.append(
            SubnetValidationInput(
                netuid=int(row["netuid"]),
                pool=str(row.get("pool") or ""),
                matched=matched,
                error=row.get("error"),
            )
        )
    return out
