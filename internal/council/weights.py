"""
Council Weights — load / save / regime-aware adjustment of expert weights.

Weights persist in data/soul_map.json under `adversarial_state.council_weights`
(the canonical location read by MindmapBridge.get_expert_weights() and the
Selector). This keeps the learning loop's weight updates flowing straight
into the next pick generation.

Signal weights (per-signal, per-horizon) are also stored in the same file under
`adversarial_state.signal_weights` and are nudged individually when predictions
resolve (Option C — two-tier weighted scoring architecture).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

DEFAULT_WEIGHTS = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
SOUL_MAP_PATH = os.path.join("data", "soul_map.json")

# Signal weight learning constants (shared with resolver.py)
_LEARNING_DELTA_CORRECT = 0.02
_LEARNING_DELTA_WRONG = -0.03
_LEARNING_MIN_WEIGHT = 0.1
_LEARNING_MAX_WEIGHT = 2.0

# Per-signal, per-horizon default weights
DEFAULT_SIGNAL_WEIGHTS: Dict[str, Dict[str, float]] = {
    "hour": {
        "rsi_crossover": 1.0,
        "macd_cross": 1.0,
        "stochastic_reversal": 1.0,
        "momentum_shift": 1.0,
        "bollinger_squeeze": 1.0,
        "mfi_flow": 1.0,
        "cci_divergence": 1.0,
        "williams_r": 1.0,
        "keltner_channel": 1.0,
        "delegation_flow": 1.0,
        "staking_conviction": 1.0,
        "emission_momentum": 1.0,
        "registration_cost": 1.0,
    },
    "day": {
        "rsi_crossover": 1.0,
        "macd_cross": 1.0,
        "stochastic_reversal": 1.0,
        "momentum_shift": 1.0,
        "bollinger_squeeze": 1.0,
        "mfi_flow": 1.0,
        "cci_divergence": 1.0,
        "williams_r": 1.0,
        "keltner_channel": 1.0,
        "delegation_flow": 1.0,
        "staking_conviction": 1.0,
        "emission_momentum": 1.0,
        "registration_cost": 1.0,
    },
}

# Regime -> per-expert multiplier. >1 boosts, <1 dampens.
REGIME_ADJUSTMENTS: Dict[str, Dict[str, float]] = {
    "risk_on": {"quant": 1.05, "hype": 1.10, "dark_horse": 0.95, "technical": 1.05},
    "risk_off": {"quant": 1.05, "hype": 0.85, "dark_horse": 1.10, "technical": 1.05},
    "chop": {"quant": 1.00, "hype": 0.95, "dark_horse": 1.00, "technical": 1.00},
    "high_volatility": {"quant": 0.95, "hype": 1.05, "dark_horse": 0.95, "technical": 1.10},
}


def _load_raw(path: str = SOUL_MAP_PATH) -> Dict[str, Any]:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_raw(data: Dict[str, Any], path: str = SOUL_MAP_PATH) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


def load_weights(path: str = SOUL_MAP_PATH) -> Dict[str, float]:
    """Read learned weights from soul_map.json, defaulting to DEFAULT_WEIGHTS."""
    data = _load_raw(path)
    adv = data.get("adversarial_state")
    if isinstance(adv, dict) and isinstance(adv.get("council_weights"), dict):
        cw = {k: float(v) for k, v in adv["council_weights"].items()}
        # Ensure all canonical experts are present.
        for name, default in DEFAULT_WEIGHTS.items():
            cw.setdefault(name, default)
        return cw
    sms = data.get("soul_map_state")
    if isinstance(sms, dict) and isinstance(sms.get("expert_weights"), dict):
        return {k: float(v) for k, v in sms["expert_weights"].items()}
    if isinstance(data.get("expert_weights"), dict):
        return {k: float(v) for k, v in data["expert_weights"].items()}
    return dict(DEFAULT_WEIGHTS)


def save_weights(weights: Dict[str, float], path: str = SOUL_MAP_PATH) -> None:
    """Persist weights to adversarial_state.council_weights (canonical slot)."""
    data = _load_raw(path)
    adv = data.setdefault("adversarial_state", {})
    if not isinstance(adv, dict):
        adv = {}
        data["adversarial_state"] = adv
    adv["council_weights"] = {k: round(float(v), 4) for k, v in weights.items()}
    adv["last_weight_update"] = _now_iso()
    _save_raw(data, path)


def detect_regime(market_data: Optional[Dict[str, Any]] = None) -> str:
    """Classify the market regime from aggregate market intelligence."""
    market_data = market_data or {}
    avg_change = float(market_data.get("avg_change_24h", 0) or 0)
    breadth = str(market_data.get("breadth", "neutral")).lower()
    volatility = float(market_data.get("volatility", 0) or 0)
    gainers = int(market_data.get("gainers", 0) or 0)
    losers = int(market_data.get("losers", 0) or 0)

    if volatility >= 8 or abs(avg_change) >= 8:
        return "high_volatility"
    if breadth == "bullish" or (gainers > losers * 1.5 and avg_change > 2):
        return "risk_on"
    if breadth == "bearish" or (losers > gainers * 1.5 and avg_change < -2):
        return "risk_off"
    return "chop"


def apply_regime_adjustment(
    weights: Dict[str, float], regime: str
) -> Dict[str, float]:
    """Apply regime multipliers to a weight dict (does not normalize)."""
    adj = REGIME_ADJUSTMENTS.get(regime, {})
    adjusted = {}
    for name, w in weights.items():
        adjusted[name] = w * adj.get(name, 1.0)
    return adjusted


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Signal weights (per-signal, per-horizon)
# ---------------------------------------------------------------------------

def load_signal_weights(path: str = SOUL_MAP_PATH) -> Dict[str, Dict[str, float]]:
    """Read learned signal weights from soul_map.json, defaulting to DEFAULT_SIGNAL_WEIGHTS."""
    data = _load_raw(path)
    adv = data.get("adversarial_state")
    if isinstance(adv, dict) and isinstance(adv.get("signal_weights"), dict):
        raw = adv["signal_weights"]
        signal_weights = dict(DEFAULT_SIGNAL_WEIGHTS)
        for horizon in ("hour", "day"):
            if isinstance(raw.get(horizon), dict):
                for signal_name, default_val in DEFAULT_SIGNAL_WEIGHTS[horizon].items():
                    signal_weights[horizon][signal_name] = float(raw[horizon].get(signal_name, default_val))
        return signal_weights
    return dict(DEFAULT_SIGNAL_WEIGHTS)


def save_signal_weights(
    signal_weights: Dict[str, Dict[str, float]],
    path: str = SOUL_MAP_PATH,
) -> None:
    """Persist signal weights to adversarial_state.signal_weights."""
    data = _load_raw(path)
    adv = data.setdefault("adversarial_state", {})
    if not isinstance(adv, dict):
        adv = {}
        data["adversarial_state"] = adv
    adv["signal_weights"] = {
        horizon: {k: round(float(v), 4) for k, v in weights.items()}
        for horizon, weights in signal_weights.items()
    }
    _save_raw(data, path)


def nudge_signal_weight(
    horizon_type: str,
    signal_name: str,
    correct: bool,
    path: str = SOUL_MAP_PATH,
) -> None:
    """Nudge a single signal weight up (correct) or down (wrong), clamped to [0.1, 2.0]."""
    signal_weights = load_signal_weights(path)
    horizon_weights = signal_weights.setdefault(horizon_type, {})
    delta = _LEARNING_DELTA_CORRECT if correct else _LEARNING_DELTA_WRONG
    current = horizon_weights.get(signal_name, 1.0)
    new_val = max(_LEARNING_MIN_WEIGHT, min(_LEARNING_MAX_WEIGHT, current + delta))
    horizon_weights[signal_name] = round(new_val, 4)
    save_signal_weights(signal_weights, path)


def compute_weighted_signal_score(
    signal_values: Dict[str, float],
    horizon_type: str,
    signal_weights: Dict[str, Dict[str, float]],
) -> float:
    """Compute weighted average of signal values using per-horizon signal weights."""
    horizon_weights = signal_weights.get(horizon_type, signal_weights.get("day", {}))
    weighted_sum = 0.0
    total_weight = 0.0
    for signal_name, value in signal_values.items():
        weight = horizon_weights.get(signal_name, 1.0)
        weighted_sum += value * weight
        total_weight += weight
    return round(weighted_sum / total_weight, 4) if total_weight > 0 else 0.5
