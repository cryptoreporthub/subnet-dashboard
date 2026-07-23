"""Frozen claim-time feature vectors for Upgrade 6 (XGBoost) prep.

Schema is append-only: bump FEATURE_SCHEMA_VERSION when adding keys.
Vectors are frozen at pump_lead claim time so labels grade against the
same features that fired — never recompute from live state at train time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Bump when adding keys (old rows stay valid for their version).
FEATURE_SCHEMA_VERSION = 1

# Ordered feature names for matrix columns (schema v1).
FEATURE_KEYS: Tuple[str, ...] = (
    "buy_ratio",
    "volume_intensity",
    "composite_score",
    "triad_lit_count",
    "price_change_24h",
    "momentum_1h",
    "chatter_intensity",
    "hour_utc",
    "phase_code",
)

_PHASE_CODE = {
    "STIRRING": 1.0,
    "ACCUMULATING": 2.0,
    "JUST_STARTED": 3.0,
    "JUST STARTED": 3.0,
}


def _f(raw: Any, default: float = 0.0) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


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


def _triad_lit_count(snap: Dict[str, Any]) -> float:
    if snap.get("triad_lit_count") is not None:
        return _f(snap.get("triad_lit_count"), 0.0)
    triad = snap.get("triad")
    if isinstance(triad, dict):
        return float(
            sum(
                1
                for k in ("inflow_quiet_load", "buy_pressure", "price_coil")
                if triad.get(k)
            )
        )
    return 0.0


def _phase_code(prediction: Dict[str, Any], snap: Dict[str, Any]) -> float:
    for key in ("pump_claim", "pump_phase", "phase"):
        code = _PHASE_CODE.get(str(prediction.get(key) or "").upper())
        if code is not None:
            return code
    code = _PHASE_CODE.get(str(snap.get("phase") or "").upper())
    return code if code is not None else 0.0


def freeze_feature_vector(
    signal_snapshot: Optional[Dict[str, Any]],
    *,
    composite_score: float = 0.0,
    created_at: Optional[Any] = None,
    prediction: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """Build a numeric feature dict from claim-time signals (schema v1)."""
    snap = signal_snapshot if isinstance(signal_snapshot, dict) else {}
    pred = prediction if isinstance(prediction, dict) else {}
    created = _parse_ts(created_at) or _parse_ts(pred.get("created_at"))
    hour = float(created.hour) if created else 0.0
    score = composite_score
    if score == 0.0 and pred.get("composite_score") is not None:
        score = _f(pred.get("composite_score"), 0.0)
    if score == 0.0 and snap.get("composite_score") is not None:
        score = _f(snap.get("composite_score"), 0.0)

    return {
        "buy_ratio": _f(snap.get("buy_ratio"), 0.5),
        "volume_intensity": _f(snap.get("volume_intensity"), 0.0),
        "composite_score": _f(score, 0.0),
        "triad_lit_count": _triad_lit_count(snap),
        "price_change_24h": _f(snap.get("price_change_24h"), 0.0),
        "momentum_1h": _f(snap.get("momentum_1h"), 0.0),
        "chatter_intensity": _f(snap.get("chatter_intensity"), 0.0),
        "hour_utc": hour,
        "phase_code": _phase_code(pred, snap),
    }


def feature_row_from_prediction(prediction: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Prefer frozen vector on the row; else rebuild from signal_snapshot (legacy)."""
    frozen = prediction.get("feature_vector")
    if isinstance(frozen, dict) and frozen:
        # Normalize to schema keys only (floats).
        return {k: _f(frozen.get(k), 0.0) for k in FEATURE_KEYS}
    snap = prediction.get("signal_snapshot")
    if not isinstance(snap, dict):
        return None
    return freeze_feature_vector(
        snap,
        composite_score=_f(prediction.get("composite_score"), 0.0),
        created_at=prediction.get("created_at"),
        prediction=prediction,
    )


def vector_as_list(features: Dict[str, float]) -> List[float]:
    return [_f(features.get(k), 0.0) for k in FEATURE_KEYS]


def attach_frozen_features(
    prediction: Dict[str, Any],
    *,
    signal_snapshot: Optional[Dict[str, Any]] = None,
    composite_score: float = 0.0,
) -> Dict[str, Any]:
    """Mutate prediction with feature_vector + schema version; return it."""
    snap = signal_snapshot
    if snap is None:
        raw = prediction.get("signal_snapshot")
        snap = raw if isinstance(raw, dict) else {}
    vec = freeze_feature_vector(
        snap,
        composite_score=composite_score,
        created_at=prediction.get("created_at"),
        prediction=prediction,
    )
    prediction["feature_schema_version"] = FEATURE_SCHEMA_VERSION
    prediction["feature_vector"] = vec
    prediction["feature_keys"] = list(FEATURE_KEYS)
    return prediction
