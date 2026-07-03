"""
5-Phase Conviction Ladder for Prediction System.

Conviction phases map confidence levels to market cycle states:
  Phase 1: 🔥 EARLY (0-25% confidence) - Initial signal, low conviction
  Phase 2: ⚠️ EXHAUSTING (25-50% confidence, overbought signals) - Momentum fading
  Phase 3: ⏸️ CONSOLIDATING (50-75% confidence, pullback) - Accumulation phase
  Phase 4: 🚀 SECOND_WIND (75-90% confidence, accumulation) - Renewed momentum
  Phase 5: 🚨 SELL (90-100% confidence, exit signal) - Peak conviction, time to exit

This module provides:
  - Conviction phase computation from confidence scores
  - Integration with pump tracker for phase state
  - Outcome recording for the learning loop
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 5-Phase Conviction Ladder definition
CONVICTION_PHASES = {
    1: {"name": "EARLY", "emoji": "🔥", "min_conf": 0, "max_conf": 25, "description": "Initial signal, low conviction"},
    2: {"name": "EXHAUSTING", "emoji": "⚠️", "min_conf": 25, "max_conf": 50, "description": "Momentum fading, overbought signals"},
    3: {"name": "CONSOLIDATING", "emoji": "⏸️", "min_conf": 50, "max_conf": 75, "description": "Pullback, accumulation phase"},
    4: {"name": "SECOND_WIND", "emoji": "🚀", "min_conf": 75, "max_conf": 90, "description": "Renewed momentum, accumulation"},
    5: {"name": "SELL", "emoji": "🚨", "min_conf": 90, "max_conf": 100, "description": "Peak conviction, exit signal"},
}

# Phase color mapping for UI badges
PHASE_COLORS = {
    1: "phase-early",      # Red/orange
    2: "phase-exhausting", # Yellow/amber
    3: "phase-consolidating", # Blue
    4: "phase-second-wind", # Green
    5: "phase-sell",       # Red alert
}

OUTCOMES_PATH = os.path.join("data", "outcomes.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_conviction_phase(confidence: float) -> int:
    """Map a confidence score (0-100) to a conviction phase (1-5)."""
    confidence = max(0, min(100, float(confidence or 0)))
    for phase, data in sorted(CONVICTION_PHASES.items()):
        if data["min_conf"] <= confidence <= data["max_conf"]:
            return phase
    return 1


def get_phase_info(phase: int) -> Dict[str, Any]:
    """Return phase metadata (name, emoji, description, color class)."""
    data = CONVICTION_PHASES.get(phase, CONVICTION_PHASES[1])
    return {
        "phase": phase,
        "name": data["name"],
        "emoji": data["emoji"],
        "description": data["description"],
        "color_class": PHASE_COLORS.get(phase, "phase-early"),
        "min_confidence": data["min_conf"],
        "max_confidence": data["max_conf"],
    }


def compute_conviction_for_prediction(
    prediction: Dict[str, Any],
    pump_state: Optional[Dict[str, Any]] = None,
    technical_indicators: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute conviction phase and confidence for a prediction.

    Combines:
      - Base confidence from prediction (if available)
      - Pump cycle phase state
      - Technical indicator signals (RSI overbought/oversold)
    """
    # Start with base confidence
    base_confidence = float(prediction.get("confidence", 0) or 0)
    if base_confidence == 0:
        # Derive from predicted_pct magnitude if no explicit confidence
        predicted_pct = abs(float(prediction.get("predicted_pct", 0) or 0))
        base_confidence = min(100, predicted_pct * 10)  # Scale: 10% move = 100% confidence

    # Adjust based on pump phase if available
    if pump_state:
        pump_phase = pump_state.get("current_phase", "ACCUMULATION")
        # Map pump phases to conviction adjustments
        phase_adjustments = {
            "ACCUMULATION": -10,   # Lower confidence in early phase
            "MARKUP": 15,         # Higher confidence during markup
            "PARABOLIC": 25,      # Highest confidence during parabolic
            "DISTRIBUTION": 10,   # Moderate confidence in distribution
            "DECLINE": -20,       # Lower confidence in decline
            "RE_ACCUMULATION": -5, # Slightly lower in re-accumulation
        }
        base_confidence += phase_adjustments.get(pump_phase, 0)

    # Adjust based on technical indicators
    if technical_indicators:
        rsi = technical_indicators.get("rsi")
        if isinstance(rsi, (int, float)):
            if rsi > 70:  # Overbought - may indicate exhaustion
                base_confidence -= 15
            elif rsi < 30:  # Oversold - may indicate early opportunity
                base_confidence += 10

    # Clamp to valid range
    confidence = max(0, min(100, base_confidence))
    phase = get_conviction_phase(confidence)

    return {
        "conviction_phase": phase,
        "phase_confidence": round(confidence, 1),
        "phase_changed_at": _now_iso(),
    }


def record_outcome(
    netuid: int,
    prediction_id: str,
    outcome: str,
    actual_pct: float,
    confidence: float,
    phase: int,
    expert: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a prediction outcome for the learning loop.

    Args:
        netuid: Subnet ID
        prediction_id: Prediction identifier
        outcome: "hit", "partial", or "miss"
        actual_pct: Actual percentage move realized
        confidence: Confidence at time of prediction
        phase: Conviction phase at time of prediction
        expert: Canonical expert (quant/hype/contrarian/technical)

    Returns:
        The recorded outcome record
    """
    outcomes = _load_outcomes()
    
    record = {
        "id": f"{netuid}_{prediction_id}",
        "netuid": netuid,
        "prediction_id": prediction_id,
        "outcome": outcome,
        "actual_pct": actual_pct,
        "predicted_confidence": confidence,
        "conviction_phase": phase,
        "expert": expert,
        "recorded_at": _now_iso(),
    }
    
    outcomes["outcomes"].append(record)
    outcomes["stats"]["total"] = outcomes.get("stats", {}).get("total", 0) + 1
    
    if outcome == "hit":
        outcomes["stats"]["hits"] = outcomes.get("stats", {}).get("hits", 0) + 1
    elif outcome == "miss":
        outcomes["stats"]["misses"] = outcomes.get("stats", {}).get("misses", 0) + 1
    
    # Update phase accuracy tracking
    phase_key = f"phase_{phase}"
    outcomes["stats"].setdefault(phase_key, {"hits": 0, "misses": 0})
    if outcome == "hit":
        outcomes["stats"][phase_key]["hits"] += 1
    elif outcome == "miss":
        outcomes["stats"][phase_key]["misses"] += 1
    
    _save_outcomes(outcomes)
    
    # Also record in scenario memory for learning loop
    try:
        from internal.council import scenario_memory
        scenario_memory.add_scenario(
            name=f"outcome_{netuid}_{prediction_id}",
            features={
                "netuid": netuid,
                "prediction_id": prediction_id,
                "outcome": outcome,
                "actual_pct": actual_pct,
                "confidence": confidence,
                "conviction_phase": phase,
                "expert": expert,
            },
            outcome="correct" if outcome == "hit" else "wrong",
        )
    except Exception as exc:
        logger.warning("Could not record outcome in scenario memory: %s", exc)
    
    return record


def _load_outcomes() -> Dict[str, Any]:
    """Load outcomes from disk."""
    try:
        with open(OUTCOMES_PATH, "r") as f:
            data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("outcomes", [])
                data.setdefault("stats", {"total": 0, "hits": 0, "misses": 0})
                return data
    except Exception:
        pass
    return {"outcomes": [], "stats": {"total": 0, "hits": 0, "misses": 0}}


def _save_outcomes(data: Dict[str, Any]) -> None:
    """Persist outcomes to disk."""
    try:
        from internal.file_utils import safe_write_json
        safe_write_json(OUTCOMES_PATH, data)
    except Exception as exc:
        logger.warning("Could not save outcomes: %s", exc)


def get_outcomes(limit: int = 100) -> List[Dict[str, Any]]:
    """Return recent outcomes for SSE streaming."""
    outcomes = _load_outcomes()
    return outcomes.get("outcomes", [])[-limit:]


def get_pump_profile(netuid: int) -> Dict[str, Any]:
    """Get pump personality profile for a subnet.

    Returns:
        - first_pump_magnitude: Average magnitude of first pump in cycle
        - re_pump_rate: Frequency of re-pumps after initial cycle
        - historical_accuracy: Accuracy of predictions in this subnet
    """
    try:
        from datastore.pump_tracker import PumpTracker
        tracker = PumpTracker()
        profile = tracker.profiles.get(netuid, {})
        cycles = tracker.cycles.get(netuid, [])
        
        # Calculate first pump magnitude
        first_pump_magnitude = 0.0
        if cycles:
            first_pumps = [c for c in cycles if c.get("phase") == "MARKUP"]
            if first_pumps:
                magnitudes = [abs(c.get("pct_move", 0)) for c in first_pumps]
                first_pump_magnitude = sum(magnitudes) / len(magnitudes) if magnitudes else 0.0
        
        # Calculate re-pump rate
        re_pump_count = len([c for c in cycles if c.get("phase") in ("MARKUP", "PARABOLIC") and c.get("re_pump", False)])
        re_pump_rate = re_pump_count / len(cycles) if cycles else 0.0
        
        # Get historical accuracy from outcomes
        outcomes = _load_outcomes()
        subnet_outcomes = [o for o in outcomes.get("outcomes", []) if o.get("netuid") == netuid]
        hits = sum(1 for o in subnet_outcomes if o.get("outcome") == "hit")
        total = len(subnet_outcomes)
        historical_accuracy = hits / total if total > 0 else 0.0
        
        return {
            "netuid": netuid,
            "first_pump_magnitude": round(first_pump_magnitude, 2),
            "re_pump_rate": round(re_pump_rate, 3),
            "historical_accuracy": round(historical_accuracy, 3),
            "total_cycles": len(cycles),
            "total_outcomes": total,
        }
    except Exception as exc:
        logger.warning("Could not get pump profile for %s: %s", netuid, exc)
        return {
            "netuid": netuid,
            "first_pump_magnitude": 0.0,
            "re_pump_rate": 0.0,
            "historical_accuracy": 0.0,
            "total_cycles": 0,
            "total_outcomes": 0,
        }