"""Pump desk calibration — separate weight namespace from council experts.

Adapt lead gates + phase entry thresholds only after n≥~30 graded early
pump_lead outcomes (LOCK step 4). Never writes soul_map council weights.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from internal.file_utils import safe_read_json, safe_write_json

logger = logging.getLogger(__name__)

CALIBRATION_PATH = os.environ.get("PUMP_CALIBRATION_PATH", "data/pump_calibration.json")
MIN_ADAPT_SAMPLE = 30

_DEFAULTS: Dict[str, Any] = {
    "version": 1,
    "lead_buy_ratio_min": 0.55,
    "lead_volume_intensity_min": 0.22,
    "just_started_max_score": 0.72,
    "phase_entry": {
        "STIRRING": 0.22,
        "ACCUMULATING": 0.42,
        "PUMPING": 0.62,
    },
    "blend_weights": {
        "volume": 0.30,
        "momentum": 0.25,
        "price": 0.20,
        "flow": 0.10,
        "chatter": 0.10,
    },
    "adapted_at": None,
    "adapted_from_n": 0,
    "adapted_from_ledger": None,
    "adapted_from_population": None,
    "adapted_from_fingerprint": None,
    "calibration_history": [],
}


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_calibration() -> Dict[str, Any]:
    return dict(_DEFAULTS)


def load_calibration(path: Optional[str] = None) -> Dict[str, Any]:
    resolved = path or CALIBRATION_PATH
    data = safe_read_json(resolved, default={})
    if not isinstance(data, dict) or not data:
        return default_calibration()
    out = default_calibration()
    out.update(
        {
            k: v
            for k, v in data.items()
            if k in out or k in ("adapted_at", "adapted_from_n", "version")
        }
    )
    if isinstance(data.get("phase_entry"), dict):
        pe = dict(out["phase_entry"])
        pe.update({k: float(v) for k, v in data["phase_entry"].items() if k in pe})
        out["phase_entry"] = pe
    if isinstance(data.get("blend_weights"), dict):
        bw = dict(out["blend_weights"])
        bw.update({k: float(v) for k, v in data["blend_weights"].items() if k in bw})
        out["blend_weights"] = bw
    return out


def save_calibration(data: Dict[str, Any], path: Optional[str] = None) -> None:
    safe_write_json(path or CALIBRATION_PATH, data)


def effective_lead_gates(cal: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    c = cal or load_calibration()
    return {
        "buy_ratio_min": float(c.get("lead_buy_ratio_min") or 0.55),
        "volume_intensity_min": float(c.get("lead_volume_intensity_min") or 0.22),
        "just_started_max_score": float(c.get("just_started_max_score") or 0.72),
    }


def effective_phase_entry(cal: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    from internal.pump.constants import PHASE_ENTRY_THRESHOLDS

    base = dict(PHASE_ENTRY_THRESHOLDS)
    c = cal or load_calibration()
    pe = c.get("phase_entry") if isinstance(c.get("phase_entry"), dict) else {}
    for k, v in pe.items():
        try:
            base[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return base


def _online_update_blend_weights(
    cal: Dict[str, Any],
    prediction: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply a bounded per-grade update to pump blend weights."""
    snap = prediction.get("signal_snapshot") if isinstance(prediction, dict) else {}
    if not isinstance(snap, dict):
        return cal
    correct = bool(prediction.get("correct"))
    features = {
        "volume": float(snap.get("volume_intensity") or 0.0),
        "momentum": min(max(float(snap.get("momentum_1h") or 0.0) / 0.04, 0.0), 1.0),
        "price": min(max(float(snap.get("price_change_24h") or 0.0) / 0.08, 0.0), 1.0),
        "flow": max(float(snap.get("buy_ratio") or 0.5) - 0.5, 0.0) * 2.0,
        "chatter": float(snap.get("chatter_intensity") or 0.0),
    }
    weights = dict(cal.get("blend_weights") or {})
    learning_rate = 0.005
    for name, value in features.items():
        direction = 1.0 if correct else -1.0
        centered = value - 0.5
        weights[name] = max(0.02, float(weights.get(name, 0.1)) + learning_rate * direction * centered)
    total = sum(weights.values())
    if total > 0:
        weights = {key: round(value / total * 0.95, 4) for key, value in weights.items()}
    cal["blend_weights"] = weights
    cal["last_online_update_at"] = _utcnow_z()
    cal["online_updates"] = int(cal.get("online_updates") or 0) + 1
    return cal


def maybe_adapt_after_resolve(
    *,
    min_sample: int = MIN_ADAPT_SAMPLE,
    prediction: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Nudge pump knobs from early-alert hit rate when n is large enough.

    Conservative: only tighten lead gates when hit rate is weak; loosen slightly
    when strong. Caps prevent runaway.
    """
    from internal.learning.pump_lead_stats import build_pump_desk_trust, pump_evidence_snapshot
    from internal.learning import pump_lead_train

    trust = build_pump_desk_trust()
    evidence = pump_evidence_snapshot()
    early = trust.get("early") or {}
    n = int(early.get("n") or 0)
    rate = early.get("hit_rate")
    cal = load_calibration()
    if prediction is not None:
        cal = _online_update_blend_weights(cal, prediction)
        save_calibration(cal)
        if n < int(min_sample):
            return cal
    if n < int(min_sample) or rate is None:
        return None
    evaluation = pump_lead_train.build_pump_evaluation()
    try:
        pump_lead_train.persist_pump_evaluation(evaluation)
    except Exception:
        logger.exception("pump evaluation persistence failed")
    if not (evaluation.get("adaptation_gate") or {}).get("passed"):
        logger.info(
            "pump calibration held: evaluation status=%s",
            evaluation.get("status"),
        )
        return None
    same_population = (
        cal.get("adapted_from_ledger") == evidence.get("ledger")
        and cal.get("adapted_from_population") == evidence.get("population")
        and cal.get("adapted_from_fingerprint") == evidence.get("fingerprint")
    )
    if same_population and int(cal.get("adapted_from_n") or 0) >= n and cal.get("adapted_at"):
        # Already adapted for this exact sample population — wait for more grades.
        if n - int(cal.get("adapted_from_n") or 0) < 5:
            return None

    buy = float(cal.get("lead_buy_ratio_min") or 0.55)
    vol = float(cal.get("lead_volume_intensity_min") or 0.22)
    stir = float((cal.get("phase_entry") or {}).get("STIRRING") or 0.22)
    accum = float((cal.get("phase_entry") or {}).get("ACCUMULATING") or 0.42)

    # Weak desk → raise bars (fewer false leads). Strong → ease slightly.
    if rate < 0.35:
        buy = min(0.70, buy + 0.02)
        vol = min(0.40, vol + 0.02)
        stir = min(0.35, stir + 0.02)
        accum = min(0.55, accum + 0.02)
    elif rate > 0.55:
        buy = max(0.50, buy - 0.01)
        vol = max(0.15, vol - 0.01)
        stir = max(0.15, stir - 0.01)
        accum = max(0.35, accum - 0.01)
    else:
        return None  # mid band — leave knobs alone

    old_version = int(cal.get("version") or 1)
    history = cal.get("calibration_history")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "version": old_version,
            "adapted_at": cal.get("adapted_at"),
            "adapted_from_n": cal.get("adapted_from_n", 0),
            "hit_rate": cal.get("last_adapt_hit_rate"),
        }
    )
    cal["calibration_history"] = history[-50:]
    cal["version"] = old_version + 1
    cal["lead_buy_ratio_min"] = round(buy, 4)
    cal["lead_volume_intensity_min"] = round(vol, 4)
    pe = dict(cal.get("phase_entry") or {})
    pe["STIRRING"] = round(stir, 4)
    pe["ACCUMULATING"] = round(accum, 4)
    cal["phase_entry"] = pe
    cal["adapted_at"] = _utcnow_z()
    cal["adapted_from_n"] = n
    cal["last_adapt_hit_rate"] = rate
    cal["adapted_from_ledger"] = evidence["ledger"]
    cal["adapted_from_population"] = evidence["population"]
    cal["adapted_from_fingerprint"] = evidence["fingerprint"]
    save_calibration(cal)
    logger.info(
        "pump_calibration adapted n=%s hit_rate=%s buy=%.2f vol=%.2f",
        n,
        rate,
        buy,
        vol,
    )
    return cal
