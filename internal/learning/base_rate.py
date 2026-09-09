"""P0.2 — unconditional +2% within-1h base-rate benchmark (aggregation only).

Computes what the market does with NO signal: for each subnet price series,
how often price reaches +CLAIM_PCT within the next 1h window. Buckets by
pattern_class from the pump pattern ledger when available.

UNFREEZE SIGNIFICANCE BAR (P1.5 — documented here so it cannot be a glance):
  A signal-conditioned regime may be treated as having edge over base rate
  only when ALL of the following hold on the post-deploy sample:
    1. N >= UNFREEZE_MIN_N (default 100) gradeable observations
    2. 95% Wilson interval is computed for the signal-conditioned hit rate
    3. Wilson lower bound of the signal-conditioned rate is STRICTLY ABOVE
       the unconditional base-rate point estimate for the same claim
       (+2% within 1h)
  Council 50.5% remains terminal-graded and UNAUDITED for measurement bias
  until P0.-2 completes; it must not clear this bar by itself.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

CLAIM_PCT = 2.0
HORIZON_HOURS = 1.0
WILSON_Z = 1.96
UNFREEZE_MIN_N = 100
UNFREEZE_BAR_TEXT = (
    "Wilson lower bound (95%) of the signal-conditioned +2%/1h hit rate "
    f"strictly above the unconditional base-rate point estimate, with "
    f"N >= {UNFREEZE_MIN_N}."
)

# Brief-cited terminal figures (not recomputed here).
EARLY_PUMP_TERMINAL_PCT = 34.8
JUST_STARTED_TERMINAL_PCT = 43.8
COUNCIL_TERMINAL_PCT = 50.5
COUNCIL_LABEL = (
    "Council 50.5% (terminal-graded; UNAUDITED for measurement bias)"
)


def wilson_binomial_ci(
    hits: int,
    n: int,
    *,
    z: float = WILSON_Z,
) -> Dict[str, Optional[float]]:
    """Wilson score interval at the given z (default 95% → z=1.96)."""
    if n <= 0:
        return {"low": None, "high": None, "centre": None}
    if hits < 0 or hits > n:
        raise ValueError(f"hits={hits} out of range for n={n}")
    p = hits / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2.0 * n)) / denom
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n) / denom
    return {
        "low": round(max(0.0, centre - margin), 4),
        "high": round(min(1.0, centre + margin), 4),
        "centre": round(centre, 4),
    }


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


def observation_hit_within_1h(
    reference_price: float,
    window_candles: Sequence[Dict[str, Any]],
    *,
    claim_pct: float = CLAIM_PCT,
) -> bool:
    """True if any favorable high in the window reaches +claim_pct vs ref."""
    ref = float(reference_price or 0)
    if ref <= 0:
        return False
    threshold = ref * (1.0 + float(claim_pct) / 100.0)
    for candle in window_candles:
        if not isinstance(candle, dict):
            continue
        try:
            high = float(candle.get("high", candle.get("close") or 0) or 0)
        except (TypeError, ValueError):
            continue
        if high >= threshold:
            return True
    return False


def iter_unconditional_observations(
    candles: Sequence[Dict[str, Any]],
    *,
    claim_pct: float = CLAIM_PCT,
    horizon_hours: float = HORIZON_HOURS,
) -> List[Dict[str, Any]]:
    """Build unconditional drift observations from a sorted candle series.

    Each candle close is a reference; the next ``horizon_hours`` of candles
    form the window. No signal conditioning.
    """
    timed: List[Tuple[datetime, Dict[str, Any]]] = []
    for candle in candles or []:
        if not isinstance(candle, dict):
            continue
        ts = _parse_ts(candle.get("timestamp"))
        if ts is None:
            continue
        try:
            close = float(candle.get("close") or 0)
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        timed.append((ts, candle))
    timed.sort(key=lambda x: x[0])

    out: List[Dict[str, Any]] = []
    horizon = timedelta(hours=horizon_hours)
    for i, (ts, candle) in enumerate(timed):
        ref = float(candle["close"])
        end = ts + horizon
        window = [c for (t, c) in timed[i + 1 :] if t <= end]
        # Need at least one forward candle inside the horizon to grade.
        if not window:
            continue
        hit = observation_hit_within_1h(ref, window, claim_pct=claim_pct)
        out.append(
            {
                "reference_ts": ts.isoformat().replace("+00:00", "Z"),
                "reference_price": ref,
                "hit": hit,
                "window_n": len(window),
            }
        )
    return out


def pattern_class_for_netuid(
    netuid: Any,
    *,
    pattern_ledger: Optional[Dict[str, Any]] = None,
) -> str:
    """Bucket label from pattern ledger; ``unclassified`` when unavailable."""
    try:
        if pattern_ledger is None:
            from internal.pump.pattern_ledger import typical_pattern_class

            return str(typical_pattern_class(netuid) or "unclassified")
        key = str(int(netuid))
        subnets = pattern_ledger.get("subnets") if isinstance(pattern_ledger, dict) else None
        entry = subnets.get(key) if isinstance(subnets, dict) else None
        if not isinstance(entry, dict):
            return "unclassified"
        # Prefer closed-segment classifier via live helper when possible.
        from internal.pump.pattern_ledger import classify_waveform

        segs = list(entry.get("segments") or [])
        open_seg = entry.get("open_segment")
        if isinstance(open_seg, dict):
            segs = segs + [open_seg]
        match = classify_waveform(segs)
        return str(match.get("pattern_class") or "unclassified")
    except Exception:
        return "unclassified"


def aggregate_base_rates(
    observations_by_class: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Per-class hit rates with sample sizes and 95% Wilson intervals."""
    classes: Dict[str, Any] = {}
    all_obs: List[Dict[str, Any]] = []
    for cls, rows in sorted(observations_by_class.items()):
        all_obs.extend(rows)
        hits = sum(1 for r in rows if r.get("hit"))
        n = len(rows)
        rate = round(hits / n, 4) if n else None
        ci = wilson_binomial_ci(hits, n)
        classes[cls] = {
            "n": n,
            "hits": hits,
            "hit_rate": rate,
            "wilson_95": ci,
            "claim_pct": CLAIM_PCT,
            "horizon_hours": HORIZON_HOURS,
        }
    hits = sum(1 for r in all_obs if r.get("hit"))
    n = len(all_obs)
    overall = {
        "n": n,
        "hits": hits,
        "hit_rate": round(hits / n, 4) if n else None,
        "wilson_95": wilson_binomial_ci(hits, n),
        "claim_pct": CLAIM_PCT,
        "horizon_hours": HORIZON_HOURS,
    }
    return {
        "overall": overall,
        "by_class": classes,
        "unfreeze_significance_bar": {
            "text": UNFREEZE_BAR_TEXT,
            "min_n": UNFREEZE_MIN_N,
            "confidence": 0.95,
            "rule": (
                "wilson_lower_bound(signal_conditioned) > "
                "base_rate_point_estimate"
            ),
        },
    }


def collect_observations_from_price_cache(
    price_cache: Dict[str, Any],
    *,
    pattern_ledger: Optional[Dict[str, Any]] = None,
    claim_pct: float = CLAIM_PCT,
) -> Dict[str, List[Dict[str, Any]]]:
    """Scan integer-netuid candle series; bucket by pattern class."""
    by_class: Dict[str, List[Dict[str, Any]]] = {}
    if not isinstance(price_cache, dict):
        return by_class
    for key, block in price_cache.items():
        try:
            nu = int(key)
        except (TypeError, ValueError):
            continue
        if nu < 1 or not isinstance(block, dict):
            continue
        candles = block.get("candles") or []
        if not isinstance(candles, list) or len(candles) < 2:
            continue
        obs = iter_unconditional_observations(candles, claim_pct=claim_pct)
        if not obs:
            continue
        cls = pattern_class_for_netuid(nu, pattern_ledger=pattern_ledger)
        for row in obs:
            row = dict(row)
            row["netuid"] = nu
            row["pattern_class"] = cls
            by_class.setdefault(cls, []).append(row)
    return by_class


def comparison_table(
    base: Dict[str, Any],
    *,
    mfe_hit_rates: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Side-by-side comparison rows with grading regime + audit status labels."""
    overall = (base or {}).get("overall") or {}
    base_rate = overall.get("hit_rate")
    base_n = overall.get("n")
    base_ci = overall.get("wilson_95") or {}

    def _mfe_pct(bucket_key: str) -> Tuple[Optional[float], Optional[int], str]:
        if not isinstance(mfe_hit_rates, dict):
            return None, None, "unavailable (no MFE report)"
        bucket = mfe_hit_rates.get(bucket_key) or {}
        mfe = bucket.get("mfe") or {}
        n = mfe.get("n")
        rate = mfe.get("hit_rate")
        if not n:
            return None, 0, "unavailable (MFE sample n=0; not regraded)"
        pct = round(float(rate) * 100.0, 1) if rate is not None else None
        return pct, int(n), "MFE-regraded"

    early_mfe_pct, early_mfe_n, early_mfe_status = _mfe_pct("early_pump")
    just_mfe_pct, just_mfe_n, just_mfe_status = _mfe_pct("just_started")

    rows = [
        {
            "name": "Unconditional base rate (+2% within 1h by drift)",
            "rate_pct": round(base_rate * 100.0, 1) if base_rate is not None else None,
            "n": base_n,
            "wilson_95": base_ci,
            "grading_regime": "unconditional-drift",
            "audit_status": "computed-from-price-cache",
        },
        {
            "name": "Early Pump 34.8%",
            "rate_pct": EARLY_PUMP_TERMINAL_PCT,
            "n": None,
            "wilson_95": None,
            "grading_regime": "terminal-graded",
            "audit_status": "brief-cited; old-regime terminal figure",
        },
        {
            "name": "Early Pump (MFE-regraded)",
            "rate_pct": early_mfe_pct,
            "n": early_mfe_n,
            "wilson_95": None,
            "grading_regime": "MFE-regraded" if early_mfe_pct is not None else "not-regraded",
            "audit_status": early_mfe_status,
        },
        {
            "name": "Just Started 43.8%",
            "rate_pct": JUST_STARTED_TERMINAL_PCT,
            "n": None,
            "wilson_95": None,
            "grading_regime": "terminal-graded",
            "audit_status": "brief-cited; old-regime terminal figure",
        },
        {
            "name": "Just Started (MFE-regraded)",
            "rate_pct": just_mfe_pct,
            "n": just_mfe_n,
            "wilson_95": None,
            "grading_regime": "MFE-regraded" if just_mfe_pct is not None else "not-regraded",
            "audit_status": just_mfe_status,
        },
        {
            "name": COUNCIL_LABEL,
            "rate_pct": COUNCIL_TERMINAL_PCT,
            "n": None,
            "wilson_95": None,
            "grading_regime": "terminal-graded",
            "audit_status": "UNAUDITED for measurement bias (P0.-2 not executed)",
        },
    ]
    return rows


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# P0.2 — Unconditional base-rate benchmark",
        "",
        f"**Unfreeze significance bar:** {UNFREEZE_BAR_TEXT}",
        "",
        "Council figure is labeled "
        f"**{COUNCIL_LABEL}** — P0.-2 has not audited measurement bias.",
        "",
        "## Overall base rate",
    ]
    overall = (report.get("base_rate") or {}).get("overall") or {}
    lines.append(
        f"- n={overall.get('n')} hits={overall.get('hits')} "
        f"rate={overall.get('hit_rate')} "
        f"wilson95={overall.get('wilson_95')}"
    )
    lines.extend(["", "## By pattern class", ""])
    lines.append("| class | n | hits | hit_rate | wilson_low | wilson_high |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for cls, row in ((report.get("base_rate") or {}).get("by_class") or {}).items():
        ci = row.get("wilson_95") or {}
        lines.append(
            f"| {cls} | {row.get('n')} | {row.get('hits')} | {row.get('hit_rate')} | "
            f"{ci.get('low')} | {ci.get('high')} |"
        )
    lines.extend(["", "## Comparison", ""])
    lines.append("| figure | rate_% | n | grading_regime | audit_status |")
    lines.append("|---|---:|---:|---|---|")
    for row in report.get("comparison") or []:
        lines.append(
            f"| {row.get('name')} | {row.get('rate_pct')} | {row.get('n')} | "
            f"{row.get('grading_regime')} | {row.get('audit_status')} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_base_rate_report(
    *,
    price_cache: Optional[Dict[str, Any]] = None,
    pattern_ledger: Optional[Dict[str, Any]] = None,
    mfe_hit_rates: Optional[Dict[str, Any]] = None,
    claim_pct: float = CLAIM_PCT,
) -> Dict[str, Any]:
    from internal.council.price_reference import PRICE_CACHE_PATH
    from internal.file_utils import safe_read_json
    from internal.pump.pattern_ledger import STATE_PATH as PATTERN_PATH

    cache = price_cache
    if cache is None:
        cache = safe_read_json(PRICE_CACHE_PATH, default={})
    ledger = pattern_ledger
    if ledger is None:
        ledger = safe_read_json(PATTERN_PATH, default={})

    by_class = collect_observations_from_price_cache(
        cache if isinstance(cache, dict) else {},
        pattern_ledger=ledger if isinstance(ledger, dict) else None,
        claim_pct=claim_pct,
    )
    base = aggregate_base_rates(by_class)
    comparison = comparison_table(base, mfe_hit_rates=mfe_hit_rates)
    return {
        "claim_pct": claim_pct,
        "horizon_hours": HORIZON_HOURS,
        "council_label": COUNCIL_LABEL,
        "unfreeze_significance_bar": base["unfreeze_significance_bar"],
        "base_rate": base,
        "comparison": comparison,
    }
