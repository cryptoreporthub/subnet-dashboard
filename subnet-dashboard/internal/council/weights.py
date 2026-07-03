"""
Council Weights — load / save / regime-aware adjustment of expert weights.

Weights persist in data/soul_map.json under `adversarial_state.council_weights`
(the canonical location read by MindmapBridge.get_expert_weights() and the
Selector). This keeps the learning loop's weight updates flowing straight
into the next pick generation.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

DEFAULT_WEIGHTS = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
SOUL_MAP_PATH = os.path.join("data", "soul_map.json")

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
