"""Pump desk hit-rate stats — separate from council trust banner.

Claim graded: early alerts hit +2% within 1h (JUST STARTED = still-positive).
Honesty gate before adaptive knobs (LOCK step 3).
"""

from __future__ import annotations

from typing import Any, Dict, List

from internal.council.grading import is_pump_lead

MIN_SAMPLE_FOR_TRUST = 5
MIN_SAMPLE_FOR_ADAPT = 30
_SKIP = frozenset({"duplicate", "expired", "ungradeable"})
_EARLY_CLAIMS = frozenset({"STIRRING", "ACCUMULATING", "WARMING UP", "BUILDING"})


def _is_early_claim(row: Dict[str, Any]) -> bool:
    claim = str(row.get("pump_claim") or "").upper()
    badge = str(row.get("pump_badge") or "").upper()
    if claim in {"JUST_STARTED", "JUST STARTED"} or badge == "JUST STARTED":
        return False
    if claim in _EARLY_CLAIMS or badge in {"WARMING UP", "BUILDING"}:
        return True
    # Default ledger early phases
    phase = str(row.get("pump_phase") or "").upper()
    return phase in {"STIRRING", "ACCUMULATING"}


def _gradeable_pump_rows(resolved: List[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in resolved or []:
        if not isinstance(row, dict):
            continue
        if not is_pump_lead(row):
            continue
        if row.get("outcome") in _SKIP:
            continue
        if row.get("correct") is None and row.get("actual_pct") is None:
            continue
        out.append(row)
    return out


def build_pump_desk_trust(
    predictions_data: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """UI payload for Lead scanner trust line."""
    if predictions_data is None:
        try:
            from internal.learning.predictions_store import load_predictions

            predictions_data = load_predictions()
        except Exception:
            predictions_data = {"resolved": [], "predictions": []}

    rows = _gradeable_pump_rows(predictions_data.get("resolved") or [])
    early = [r for r in rows if _is_early_claim(r)]
    just = [r for r in rows if not _is_early_claim(r)]

    def _bucket(bucket: List[Dict[str, Any]]) -> Dict[str, Any]:
        hits = sum(1 for r in bucket if r.get("correct") is True)
        n = len(bucket)
        rate = round(hits / n, 3) if n else None
        return {"n": n, "hits": hits, "hit_rate": rate}

    early_stats = _bucket(early)
    just_stats = _bucket(just)
    n = early_stats["n"]
    rate = early_stats["hit_rate"]
    ready = n >= MIN_SAMPLE_FOR_TRUST and rate is not None
    adapt_ready = n >= MIN_SAMPLE_FOR_ADAPT and rate is not None

    headline_pct = None
    if n == 0:
        line = "Early alerts: grading starts once lead phase entries resolve (1h)."
        message = "No graded pump leads yet"
    elif not ready:
        line = f"Early alerts: building track record ({n}/{MIN_SAMPLE_FOR_TRUST} graded)"
        message = line
    else:
        pct = round((rate or 0) * 100)
        headline_pct = pct
        line = f"Early alerts: {pct}% hit 2%+ in 1h (n={n})"
        message = None

    return {
        "ready": ready,
        "adapt_ready": adapt_ready,
        "line": line,
        "message": message,
        "headline_pct": headline_pct,
        "headline_n": n if ready else None,
        "headline_claim": "+2% in 1h from WARMING UP / BUILDING",
        "early": early_stats,
        "just_started": just_stats,
        "min_sample_trust": MIN_SAMPLE_FOR_TRUST,
        "min_sample_adapt": MIN_SAMPLE_FOR_ADAPT,
        "claim": "+2% within 1h from WARMING UP / BUILDING entry",
        "source": "predictions.json pick_source=pump_lead",
    }
