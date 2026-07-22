"""Exclusive signal_type → council expert map (no substring collisions)."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

_MAP_PATH = os.path.join("config", "signal_expert_map.json")

# Exact keys only — ``emission_momentum`` is quant, not hype via ``momentum``.
_DEFAULT_MAP: Dict[str, str] = {
    # technical
    "rsi_crossover": "technical",
    "macd_cross": "technical",
    "stochastic_reversal": "technical",
    "bollinger_squeeze": "technical",
    "mfi_flow": "technical",
    "mfi_divergence": "technical",
    "cci_divergence": "technical",
    "cci_extreme": "technical",
    "williams_r": "technical",
    "williams_r_reversal": "technical",
    "keltner_channel": "technical",
    "funding_divergence": "technical",
    # quant
    "emission_momentum": "quant",
    "emission_change": "quant",
    "staking_conviction": "quant",
    "registration_cost": "quant",
    # hype
    "momentum_shift": "hype",
    "social_sentiment": "hype",
    "whale_accumulation": "hype",
    "hot": "hype",
    # dark_horse
    "delegation_flow": "dark_horse",
    "onchain_flow": "dark_horse",
    # desk / council labels
    "sell_alert": "technical",
    "sell alert": "technical",
    "bullish": "unclassified",
    "bearish": "unclassified",
    "neutral": "unclassified",
    "market_breadth": "unclassified",
}


def _load_map() -> Dict[str, str]:
    try:
        with open(_MAP_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("signal_experts"), dict):
            raw = data["signal_experts"]
        elif isinstance(data, dict):
            raw = data
        else:
            raw = {}
        out = dict(_DEFAULT_MAP)
        for key, val in raw.items():
            if isinstance(key, str) and isinstance(val, str):
                out[key.lower().strip()] = val.lower().strip()
        return out
    except Exception:
        return dict(_DEFAULT_MAP)


SIGNAL_EXPERT_MAP = _load_map()


def _normalize_key(source: Any) -> str:
    return str(source or "").lower().strip().replace(" ", "_").replace("-", "_")


def expert_from_signal_source(source: Optional[str]) -> str:
    """Map a signal label to a council expert; unknown → unclassified."""
    if not source:
        return "unclassified"
    raw = str(source).strip()
    if not raw:
        return "unclassified"
    for key in (raw.lower(), _normalize_key(raw)):
        expert = SIGNAL_EXPERT_MAP.get(key)
        if expert in {"quant", "hype", "dark_horse", "technical", "unclassified"}:
            return expert
    return "unclassified"


def expert_from_signal_impact(signal_impact: Optional[Dict[str, Any]]) -> str:
    """Attribute from the strongest scored impact, then desk labels."""
    if not isinstance(signal_impact, dict):
        return "unclassified"
    impacts = [row for row in (signal_impact.get("impacts") or []) if isinstance(row, dict)]
    if impacts:

        def _strength(row: Dict[str, Any]) -> float:
            try:
                mag = abs(float(row.get("magnitude_pct") or 0))
            except (TypeError, ValueError):
                mag = 0.0
            try:
                weight = float(row.get("learned_weight") or 1.0)
            except (TypeError, ValueError):
                weight = 1.0
            return mag * weight

        lead = max(impacts, key=_strength)
        expert = expert_from_signal_source(str(lead.get("signal_type") or ""))
        if expert != "unclassified":
            return expert
    label = signal_impact.get("dominant") or signal_impact.get("net_direction")
    return expert_from_signal_source(str(label) if label else None)


def expert_for_replay_row(row: Dict[str, Any]) -> Optional[str]:
    """Re-derive council expert for historical replay (new map, skip pump desk)."""
    try:
        from internal.council.grading import is_pump_lead
    except Exception:
        is_pump_lead = lambda _r: False  # type: ignore
    if is_pump_lead(row):
        return None
    si = row.get("signal_impact")
    if isinstance(si, dict):
        expert = expert_from_signal_impact(si)
        if expert != "unclassified":
            return expert
    src = row.get("signal_source") or row.get("expert")
    if src:
        expert = expert_from_signal_source(str(src))
        if expert != "unclassified":
            return expert
    try:
        from internal.council.resolver import _normalize_expert

        return _normalize_expert(row)
    except Exception:
        return None


def dominant_signal_label(signal_impact: Optional[Dict[str, Any]]) -> Optional[str]:
    """Best ledger label: lead impact signal_type, else HOT/SELL, else direction."""
    if not isinstance(signal_impact, dict):
        return None
    impacts = [row for row in (signal_impact.get("impacts") or []) if isinstance(row, dict)]
    if impacts:

        def _strength(row: Dict[str, Any]) -> float:
            try:
                return abs(float(row.get("magnitude_pct") or 0)) * float(row.get("learned_weight") or 1.0)
            except (TypeError, ValueError):
                return 0.0

        lead = max(impacts, key=_strength)
        st = lead.get("signal_type")
        if st:
            return str(st)
    dom = signal_impact.get("dominant")
    if dom:
        return str(dom)
    direction = signal_impact.get("net_direction")
    return str(direction) if direction else None
