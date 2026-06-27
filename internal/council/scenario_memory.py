"""
Regime-aware scenario memory for the Council engine.

Scenarios are tagged as ``bull``, ``bear`` or ``volatile`` and persisted to
``data/scenario_memory.json`` across sessions. The memory is intentionally
lightweight so it can be read/written on every Council cycle without adding
latency to the main dashboard.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.weights import detect_regime

SCENARIO_MEMORY_PATH = os.path.join("data", "scenario_memory.json")

# Canonical scenario buckets.
REGIMES = {"bull", "bear", "volatile", "neutral"}


def _load(path: Optional[str] = None) -> Dict[str, Any]:
    path = path or SCENARIO_MEMORY_PATH
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"scenarios": [], "regimes": {r: [] for r in REGIMES}, "meta": {}}


def _save(data: Dict[str, Any], path: Optional[str] = None) -> None:
    path = path or SCENARIO_MEMORY_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data.setdefault("meta", {})
    data["meta"]["last_updated"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _normalize_regime(regime: Optional[str]) -> str:
    if not regime:
        return "neutral"
    r = regime.lower().strip()
    if r in {"bull", "bullish", "risk_on"}:
        return "bull"
    if r in {"bear", "bearish", "risk_off"}:
        return "bear"
    if r in {"volatile", "high_volatility", "choppy"}:
        return "volatile"
    return "neutral"


def classify_regime(features: Optional[Dict[str, Any]]) -> str:
    """Classify a feature set into a canonical scenario regime.

    Reuses ``weights.detect_regime`` when possible, then maps its macro
    vocabulary onto the bull/bear/volatile/neutral scenario buckets.
    """
    features = features or {}

    # Try the macro regime detector first.
    try:
        macro = detect_regime(features)
        mapped = _normalize_regime(macro)
        if mapped != "neutral":
            return mapped
    except Exception:
        pass

    avg_change = float(features.get("avg_change_24h", features.get("price_change_24h", 0)) or 0)
    volatility = float(features.get("volatility", features.get("price_volatility", 0)) or 0)
    breadth = str(features.get("breadth", "neutral")).lower()

    if volatility >= 8 or abs(avg_change) >= 8 or breadth == "volatile":
        return "volatile"
    if avg_change > 3 or breadth == "bullish":
        return "bull"
    if avg_change < -3 or breadth == "bearish":
        return "bear"
    return "neutral"


def add_scenario(
    name: str,
    features: Dict[str, Any],
    outcome: Optional[str] = None,
    regime: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Store a scenario in the regime-aware memory."""
    data = _load()
    if regime is None:
        regime = classify_regime(features)
    else:
        regime = _normalize_regime(regime)

    scenario: Dict[str, Any] = {
        "id": f"sc_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        "name": name,
        "regime": regime,
        "features": features,
        "outcome": outcome,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if metadata:
        scenario["metadata"] = metadata

    data["scenarios"].append(scenario)
    data["regimes"].setdefault(regime, []).append(scenario["id"])
    _save(data)
    return scenario


def get_scenarios(regime: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return stored scenarios, optionally filtered by regime."""
    data = _load()
    scenarios = data.get("scenarios", [])
    if regime is not None:
        regime = _normalize_regime(regime)
        scenarios = [s for s in scenarios if s.get("regime") == regime]
    if limit:
        scenarios = scenarios[-limit:]
    return scenarios


def get_regime_stats() -> Dict[str, Any]:
    """Return counts and outcome accuracy per regime bucket."""
    data = _load()
    scenarios = data.get("scenarios", [])
    stats: Dict[str, Any] = {
        "total": len(scenarios),
        "by_regime": {r: 0 for r in REGIMES},
        "accuracy": {},
    }

    outcomes_by_regime: Dict[str, List[bool]] = {r: [] for r in REGIMES}
    for s in scenarios:
        regime = _normalize_regime(s.get("regime"))
        stats["by_regime"][regime] = stats["by_regime"].get(regime, 0) + 1

        outcome = s.get("outcome")
        if outcome in {"hit", "correct", "win"}:
            outcomes_by_regime[regime].append(True)
        elif outcome in {"miss", "wrong", "loss"}:
            outcomes_by_regime[regime].append(False)

    for regime, outcomes in outcomes_by_regime.items():
        if outcomes:
            accuracy = sum(outcomes) / len(outcomes)
            stats["accuracy"][regime] = round(accuracy, 3)

    return stats


def get_memory_snapshot() -> Dict[str, Any]:
    """Return the full in-memory snapshot for API consumers."""
    data = _load()
    return {
        "scenarios": data.get("scenarios", []),
        "regimes": data.get("regimes", {r: [] for r in REGIMES}),
        "stats": get_regime_stats(),
        "meta": data.get("meta", {}),
    }
