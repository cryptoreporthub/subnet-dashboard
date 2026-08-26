"""REV 6 capture model — shared band/capture math for Phase A observe + Phase B learn.

Check order is locked (noise-first): predicted==0 → deadband on RAW actual →
direction → HIT / NEAR-HIT / below-C_MIN noise. Ledger rows are never mutated
here; callers stamp additive fields on NEW resolves only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

BAND_HIT = "hit"
BAND_NEAR_HIT = "near_hit"
BAND_NOISE = "noise"
BAND_UNGRADEABLE = "ungradeable"
BAND_MISS = "miss"
BANDS = frozenset({BAND_HIT, BAND_NEAR_HIT, BAND_NOISE, BAND_UNGRADEABLE, BAND_MISS})

REASON_PREDICTED_ZERO = "predicted_zero"
REASON_BELOW_DEADBAND = "below_deadband"
REASON_WRONG_DIRECTION = "wrong_direction"
REASON_BELOW_C_MIN = "below_c_min"

_DEFAULT_DEADBAND_PCT = 0.5
_DEFAULT_C_MIN = 0.25


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def grading_deadband_pct() -> float:
    return _env_float("GRADING_DEADBAND_PCT", _DEFAULT_DEADBAND_PCT)


def grading_c_min() -> float:
    return _env_float("GRADING_C_MIN", _DEFAULT_C_MIN)


def grading_mode() -> str:
    raw = (os.environ.get("GRADING_MODE") or "legacy").strip().lower()
    return raw if raw else "legacy"


def capture_mode_enabled() -> bool:
    return grading_mode() == "capture"


def grading_headline_mode() -> str:
    explicit = (os.environ.get("GRADING_HEADLINE_MODE") or "").strip().lower()
    if explicit in {"legacy", "dual", "strict"}:
        return explicit
    if not capture_mode_enabled():
        return "legacy"
    started = (os.environ.get("GRADING_PHASE_B_AT") or "").strip()
    if started:
        try:
            from datetime import datetime, timedelta, timezone

            start = datetime.fromisoformat(started.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) >= start + timedelta(days=14):
                return "strict"
        except ValueError:
            pass
    return "dual"


@dataclass(frozen=True)
class CaptureResult:
    band: str
    capture_raw: Optional[float]
    capture_capped: Optional[float]
    capture_reason: Optional[str]
    scale: float

    def as_fields(self) -> Dict[str, Any]:
        return {
            "band": self.band,
            "capture_raw": self.capture_raw,
            "capture_capped": self.capture_capped,
            "capture_reason": self.capture_reason,
        }


def _same_sign(predicted_pct: float, actual_pct: float) -> bool:
    return (predicted_pct > 0 and actual_pct > 0) or (predicted_pct < 0 and actual_pct < 0)


def compute_capture(
    predicted_pct: float,
    actual_pct: float,
    *,
    deadband_pct: Optional[float] = None,
    c_min: Optional[float] = None,
) -> CaptureResult:
    """Band + capture for one (predicted, actual) pair. Order is locked §2.0/§2.1."""
    deadband = grading_deadband_pct() if deadband_pct is None else float(deadband_pct)
    floor = grading_c_min() if c_min is None else float(c_min)
    try:
        pred = float(predicted_pct)
    except (TypeError, ValueError):
        pred = 0.0
    try:
        actual = float(actual_pct)
    except (TypeError, ValueError):
        actual = 0.0

    if pred == 0:
        return CaptureResult(
            BAND_UNGRADEABLE, None, None, REASON_PREDICTED_ZERO, 0.0
        )

    if abs(actual) <= deadband:
        if _same_sign(pred, actual):
            c_raw = actual / pred
            return CaptureResult(
                BAND_NOISE, c_raw, min(c_raw, 1.0), REASON_BELOW_DEADBAND, 0.0
            )
        return CaptureResult(
            BAND_NOISE, None, None, REASON_BELOW_DEADBAND, 0.0
        )

    if not _same_sign(pred, actual):
        return CaptureResult(
            BAND_MISS, None, None, REASON_WRONG_DIRECTION, -1.0
        )

    c_raw = actual / pred
    c_capped = min(c_raw, 1.0)
    if c_raw >= 1.0:
        return CaptureResult(BAND_HIT, c_raw, 1.0, None, 1.0)
    if c_raw >= floor:
        return CaptureResult(BAND_NEAR_HIT, c_raw, c_capped, None, c_capped)
    return CaptureResult(
        BAND_NOISE, c_raw, c_capped, REASON_BELOW_C_MIN, 0.0
    )


def compute_capture_for_prediction(
    prediction: Dict[str, Any],
    actual_pct: float,
    *,
    deadband_pct: Optional[float] = None,
    c_min: Optional[float] = None,
) -> CaptureResult:
    try:
        predicted = float(prediction.get("predicted_pct", 0) or 0)
    except (TypeError, ValueError):
        predicted = 0.0
    return compute_capture(
        predicted, actual_pct, deadband_pct=deadband_pct, c_min=c_min
    )


def legacy_capture_from_correct(correct: Any) -> CaptureResult:
    """§2.2 read-time fallback for historical rows without band/capture fields."""
    if correct is True:
        return CaptureResult(BAND_HIT, 1.0, 1.0, "legacy_correct", 1.0)
    return CaptureResult(BAND_MISS, None, None, "legacy_miss", -1.0)


def capture_from_row(row: Dict[str, Any]) -> CaptureResult:
    """Derive capture at read time. Never writes. Stored fields win when present.

    Pre-Phase-A rows (no band/capture) use the locked §2.2 mapping
    ``correct=True → HIT/1.0``, ``correct=False → MISS/null``. Do not recompute
    from predicted/actual — that would backfill historical rows at read time.
    """
    band = row.get("band")
    if band in BANDS:
        raw = row.get("capture_raw")
        capped = row.get("capture_capped")
        try:
            raw_f = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            raw_f = None
        try:
            capped_f = float(capped) if capped is not None else None
        except (TypeError, ValueError):
            capped_f = None
        scale = 0.0
        if band == BAND_HIT:
            scale = 1.0
        elif band == BAND_NEAR_HIT and capped_f is not None:
            scale = capped_f
        elif band == BAND_MISS:
            scale = -1.0
        return CaptureResult(
            str(band),
            raw_f,
            capped_f,
            row.get("capture_reason"),
            scale,
        )
    return legacy_capture_from_correct(row.get("correct"))


def stamp_capture_fields(prediction: Dict[str, Any], actual_pct: float) -> CaptureResult:
    """Additive stamp on a NEW resolve. Does not touch stored `correct`."""
    result = compute_capture_for_prediction(prediction, actual_pct)
    prediction.update(result.as_fields())
    return result


def nudge_multiplier(result: CaptureResult) -> Optional[float]:
    """Phase B scale: HIT 1.0, NEAR-HIT capture_capped, MISS 1.0 (flat), else skip.

    Returns None when the row must not nudge (NOISE / UNGRADEABLE).
    Positive vs negative delta is the caller's `correct` / band==MISS choice.
    """
    if result.band in {BAND_NOISE, BAND_UNGRADEABLE}:
        return None
    if result.band == BAND_MISS:
        return 1.0
    if result.band == BAND_HIT:
        return 1.0
    if result.band == BAND_NEAR_HIT:
        capped = result.capture_capped
        if capped is None:
            return None
        return float(capped)
    return None


def capture_nudge_correct(result: CaptureResult) -> Optional[bool]:
    """True for HIT/NEAR-HIT (credit), False for MISS (penalty), None to skip."""
    if result.band in {BAND_HIT, BAND_NEAR_HIT}:
        return True
    if result.band == BAND_MISS:
        return False
    return None


def apply_capture_scale(base_delta: float, result: CaptureResult) -> float:
    """Scale a signed base delta. NOISE/UNGRADEABLE → 0. MISS keeps flat penalty."""
    mult = nudge_multiplier(result)
    if mult is None:
        return 0.0
    if result.band == BAND_MISS:
        return float(base_delta)
    return float(base_delta) * float(mult)


def build_capture_telemetry(
    rows: Any,
    *,
    limit: int = 500,
) -> Dict[str, Any]:
    """Phase A observe payload for /api/ops/evidence. Read-only; never writes."""
    from collections import defaultdict

    resolved = [r for r in (rows or []) if isinstance(r, dict)][-int(limit) :]
    outcomes = {
        BAND_HIT: 0,
        BAND_NEAR_HIT: 0,
        BAND_NOISE: 0,
        BAND_UNGRADEABLE: 0,
        BAND_MISS: 0,
    }
    hist = {"0-25": 0, "25-50": 0, "50-100": 0, ">100": 0}
    by_expert: Dict[str, list] = defaultdict(list)
    per_subnet: Dict[str, list] = defaultdict(list)
    legacy_correct = 0
    legacy_n = 0
    deadband_noise = 0
    directional = 0  # hit + near_hit + miss
    sample_rows: List[Dict[str, Any]] = []

    for row in resolved:
        cap = capture_from_row(row)
        if cap.band in outcomes:
            outcomes[cap.band] += 1
        if cap.band == BAND_NOISE and cap.capture_reason == REASON_BELOW_DEADBAND:
            deadband_noise += 1
        if cap.band in {BAND_HIT, BAND_NEAR_HIT, BAND_MISS}:
            directional += 1
        if row.get("correct") is True:
            legacy_correct += 1
        if row.get("correct") is True or row.get("correct") is False:
            legacy_n += 1
        if cap.capture_raw is not None:
            pct = abs(float(cap.capture_raw)) * 100.0
            if pct > 100:
                hist[">100"] += 1
            elif pct >= 50:
                hist["50-100"] += 1
            elif pct >= 25:
                hist["25-50"] += 1
            else:
                hist["0-25"] += 1
            expert = str(row.get("expert") or "unknown")
            by_expert[expert].append(min(float(cap.capture_capped or cap.capture_raw), 1.0))
        uid = row.get("netuid")
        actual = row.get("actual_pct")
        if uid is not None and actual is not None:
            try:
                per_subnet[str(uid)].append(float(actual))
            except (TypeError, ValueError):
                pass
        sample_rows.append(
            {
                "id": row.get("id"),
                "netuid": row.get("netuid"),
                "band": cap.band,
                "capture_raw": cap.capture_raw,
                "capture_capped": cap.capture_capped,
                "capture_reason": cap.capture_reason,
            }
        )

    n = len(resolved)
    near = outcomes[BAND_NEAR_HIT]
    hits = outcomes[BAND_HIT]
    avg_by_expert = {
        name: round(sum(vals) / len(vals), 4) for name, vals in by_expert.items() if vals
    }
    vol = {}
    for uid, vals in per_subnet.items():
        if len(vals) < 2:
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        sigma = var ** 0.5
        vol[uid] = {
            "sigma_actual_pct": round(sigma, 4),
            "n": len(vals),
            "observe_band_pct": round(max(grading_deadband_pct(), sigma), 4),
        }

    return {
        "outcomes": outcomes,
        "epsilon_hit_share": round(deadband_noise / n, 4) if n else None,
        "near_hit_rate": round(near / directional, 4) if directional else None,
        "capture_histogram": hist,
        "avg_capture_by_expert": avg_by_expert,
        "hit_rate_strict": round(hits / directional, 4) if directional else None,
        "hit_rate_sign_only_legacy": round(legacy_correct / legacy_n, 4) if legacy_n else None,
        "volatility_deadband": vol,
        "rows": sample_rows,
        "headline_mode": grading_headline_mode(),
        "note": "capture window capped at last 500 resolved",
    }
