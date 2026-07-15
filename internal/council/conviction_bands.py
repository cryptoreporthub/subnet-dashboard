"""§17.S1 — conviction bands (high / medium / low) for UI honesty."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Align with hybrid / calibration floor
BAND_MIN_SAMPLE = 30

_BANDS = ("high", "medium", "low")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def expert_agreement(expert_contributions: Optional[Dict[str, Any]]) -> Optional[float]:
    """1.0 = experts aligned; 0.0 = maximally split. None if unusable."""
    if not isinstance(expert_contributions, dict) or len(expert_contributions) < 2:
        return None
    vals: List[float] = []
    for v in expert_contributions.values():
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            continue
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    var = sum((x - mean) ** 2 for x in vals) / len(vals)
    # Contributions are typically ~0–1; stdev 0.5 → agreement ~0
    stdev = var ** 0.5
    return round(_clamp01(1.0 - stdev * 2.0), 4)


def recent_direction_hit_rate(limit: int = 50) -> Dict[str, Any]:
    """Hit-rate over recent gradeable resolved rows."""
    try:
        from internal.council.grading import direction_correct
        from internal.learning.predictions_store import load_predictions
    except Exception:
        return {"n": 0, "hit_rate": None}

    skip = frozenset({"duplicate", "expired", "ungradeable"})
    rows = []
    try:
        data = load_predictions()
        for row in data.get("resolved") or []:
            if not isinstance(row, dict):
                continue
            if row.get("outcome") in skip:
                continue
            if row.get("actual_pct") is None:
                continue
            rows.append(row)
    except Exception:
        return {"n": 0, "hit_rate": None}

    rows = rows[-int(limit) :] if limit else rows
    if not rows:
        return {"n": 0, "hit_rate": None}
    hits = sum(1 for r in rows if direction_correct(r, float(r["actual_pct"])))
    return {"n": len(rows), "hit_rate": round(hits / len(rows), 4)}


def compute_conviction_band(
    *,
    confidence: Optional[float] = None,
    agreement: Optional[float] = None,
    hit_rate: Optional[float] = None,
    sample_n: int = 0,
    min_sample: int = BAND_MIN_SAMPLE,
) -> Dict[str, Any]:
    """Derive band from agreement + hit-rate (+ optional confidence).

    Cold-start / missing inputs → band null + reason (never invent medium).
    """
    if int(sample_n) < int(min_sample):
        return {
            "band": None,
            "reason": "not_enough_data",
            "message": "not enough data yet",
            "sample_n": int(sample_n),
            "min_sample": int(min_sample),
            "components": {
                "confidence": confidence,
                "agreement": agreement,
                "hit_rate": hit_rate,
            },
        }

    parts: List[float] = []
    if hit_rate is not None:
        parts.append(_clamp01(hit_rate))
    if agreement is not None:
        parts.append(_clamp01(agreement))
    if confidence is not None:
        parts.append(_clamp01(confidence))

    if not parts:
        return {
            "band": None,
            "reason": "insufficient_signal",
            "message": "not enough data yet",
            "sample_n": int(sample_n),
            "min_sample": int(min_sample),
            "components": {
                "confidence": confidence,
                "agreement": agreement,
                "hit_rate": hit_rate,
            },
        }

    score = sum(parts) / len(parts)
    if score >= 0.62:
        band: Optional[str] = "high"
    elif score >= 0.48:
        band = "medium"
    else:
        band = "low"

    return {
        "band": band,
        "score": round(score, 4),
        "reason": None,
        "message": None,
        "sample_n": int(sample_n),
        "min_sample": int(min_sample),
        "components": {
            "confidence": confidence,
            "agreement": agreement,
            "hit_rate": hit_rate,
        },
    }


def band_for_pick(pick: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Convenience: band for a council pick dict (or global hit-rate only)."""
    recent = recent_direction_hit_rate()
    agreement = None
    confidence = None
    if isinstance(pick, dict):
        agreement = expert_agreement(pick.get("expert_contributions"))
        raw = pick.get("final_confidence", pick.get("confidence"))
        try:
            confidence = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            confidence = None
    return compute_conviction_band(
        confidence=confidence,
        agreement=agreement,
        hit_rate=recent.get("hit_rate"),
        sample_n=int(recent.get("n") or 0),
    )


def conviction_bands_status() -> Dict[str, Any]:
    """API summary for calibration/learning consumers."""
    payload = band_for_pick(None)
    payload["status"] = "ok"
    return payload
