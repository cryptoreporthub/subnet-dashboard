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
    out.update({k: v for k, v in data.items() if k in out or k in ("adapted_at", "adapted_from_n", "version")})
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


def maybe_adapt_after_resolve(*, min_sample: int = MIN_ADAPT_SAMPLE) -> Optional[Dict[str, Any]]:
    """Nudge pump knobs from early-alert hit rate when n is large enough.

    Conservative: only tighten lead gates when hit rate is weak; loosen slightly
    when strong. Caps prevent runaway.
    """
    from internal.learning.pump_lead_stats import build_pump_desk_trust

    trust = build_pump_desk_trust()
    early = trust.get("early") or {}
    n = int(early.get("n") or 0)
    rate = early.get("hit_rate")
    if n < int(min_sample) or rate is None:
        return None

    cal = load_calibration()
    if int(cal.get("adapted_from_n") or 0) >= n and cal.get("adapted_at"):
        # Already adapted for this sample size — wait for more grades
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

    cal["lead_buy_ratio_min"] = round(buy, 4)
    cal["lead_volume_intensity_min"] = round(vol, 4)
    pe = dict(cal.get("phase_entry") or {})
    pe["STIRRING"] = round(stir, 4)
    pe["ACCUMULATING"] = round(accum, 4)
    cal["phase_entry"] = pe
    cal["adapted_at"] = _utcnow_z()
    cal["adapted_from_n"] = n
    cal["last_adapt_hit_rate"] = rate
    save_calibration(cal)
    logger.info(
        "pump_calibration adapted n=%s hit_rate=%s buy=%.2f vol=%.2f",
        n,
        rate,
        buy,
        vol,
    )
    return cal
