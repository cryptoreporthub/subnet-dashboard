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
    stdev = var ** 0.5
    return round(_clamp01(1.0 - stdev * 2.0), 4)


def _judge_score_value(raw: Any) -> Optional[float]:
    if isinstance(raw, dict):
        for key in ("confidence", "score"):
            if raw.get(key) is not None:
                try:
                    return _clamp01(float(raw[key]))
                except (TypeError, ValueError):
                    continue
    return None


def judge_scores_for_netuid(netuid: Optional[int]) -> Optional[Dict[str, Any]]:
    """Latest prediction judge scores for a subnet (§21 L8)."""
    if netuid is None:
        return None
    try:
        from internal.learning.predictions_store import load_predictions

        data = load_predictions()
        for bucket in ("predictions", "resolved"):
            rows = list(data.get(bucket) or [])
            for pred in reversed(rows):
                if not isinstance(pred, dict):
                    continue
                if pred.get("netuid") != netuid:
                    continue
                scores = pred.get("judge_scores_at_creation")
                if isinstance(scores, dict) and scores:
                    return scores
    except Exception:
        pass
    return None


def judge_feedback_confidence(pick: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """Mean judge confidence at pick creation; blends historical calibration (§21 L8)."""
    netuid = None
    if isinstance(pick, dict):
        sn = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else pick
        if isinstance(sn, dict):
            netuid = sn.get("netuid")
    scores = judge_scores_for_netuid(netuid)
    live_vals: List[float] = []
    if isinstance(scores, dict):
        for raw in scores.values():
            val = _judge_score_value(raw)
            if val is not None:
                live_vals.append(val)
    live = round(sum(live_vals) / len(live_vals), 4) if live_vals else None

    cal = judge_calibration_hit_rate()
    hist = cal.get("hit_rate")
    if live is not None and hist is not None:
        return round((live + float(hist)) / 2.0, 4)
    return live if live is not None else (float(hist) if hist is not None else None)


def judge_calibration_hit_rate(limit: int = 30) -> Dict[str, Any]:
    """Fraction of resolved picks where high judge confidence aligned with outcome."""
    try:
        from internal.learning.predictions_store import load_predictions
    except Exception:
        return {"n": 0, "hit_rate": None}

    skip = frozenset({"duplicate", "expired", "ungradeable"})
    aligned = 0
    total = 0
    try:
        data = load_predictions()
        rows = [r for r in (data.get("resolved") or []) if isinstance(r, dict)]
        for pred in rows[-int(limit) :]:
            if pred.get("outcome") in skip or pred.get("correct") is None:
                continue
            scores = pred.get("judge_scores_at_creation")
            if not isinstance(scores, dict) or not scores:
                continue
            vals = [_judge_score_value(v) for v in scores.values()]
            vals = [v for v in vals if v is not None]
            if not vals:
                continue
            bullish = sum(vals) / len(vals) >= 0.5
            correct = bool(pred.get("correct"))
            total += 1
            if bullish == correct:
                aligned += 1
    except Exception:
        return {"n": 0, "hit_rate": None}

    if total < 5:
        return {"n": total, "hit_rate": None}
    return {"n": total, "hit_rate": round(aligned / total, 4)}


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
    judge_conf = None
    if isinstance(pick, dict):
        agreement = expert_agreement(pick.get("expert_contributions"))
        raw = pick.get("final_confidence", pick.get("confidence"))
        try:
            confidence = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            confidence = None
        judge_conf = judge_feedback_confidence(pick)
        if confidence is None:
            confidence = judge_conf
        elif judge_conf is not None:
            confidence = round((confidence + judge_conf) / 2.0, 4)
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
