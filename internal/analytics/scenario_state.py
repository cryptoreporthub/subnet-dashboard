"""Read scenario memory snapshot without importing council modules."""

from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any, Dict, List

SCENARIO_MEMORY_PATH = os.environ.get("SCENARIO_MEMORY_PATH", "data/scenario_memory.json")
REGIMES = ("bull", "bear", "volatile", "neutral")


def load_scenario_snapshot(path: str | None = None) -> Dict[str, Any]:
    """Load scenario memory from disk in the same shape as GET /api/scenario-memory."""
    path = path or SCENARIO_MEMORY_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return _empty_snapshot()
    except Exception:
        return _empty_snapshot()

    scenarios = data.get("scenarios", [])
    if not isinstance(scenarios, list):
        scenarios = []

    stats = _regime_stats(scenarios)
    return {
        "status": "ok",
        "scenarios": scenarios,
        "regimes": data.get("regimes", {r: [] for r in REGIMES}),
        "stats": stats,
        "meta": data.get("meta", {}),
    }


def _empty_snapshot() -> Dict[str, Any]:
    return {
        "status": "ok",
        "scenarios": [],
        "regimes": {r: [] for r in REGIMES},
        "stats": {"total": 0, "by_regime": {r: 0 for r in REGIMES}, "accuracy": {}},
        "meta": {},
    }


def _regime_stats(scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_regime: Counter[str] = Counter()
    outcomes_by_regime: Dict[str, List[bool]] = {r: [] for r in REGIMES}

    for scenario in scenarios:
        regime = str(scenario.get("regime", "neutral")).lower()
        if regime not in REGIMES:
            regime = "neutral"
        by_regime[regime] += 1
        outcome = scenario.get("outcome")
        if outcome in {"hit", "correct", "win"}:
            outcomes_by_regime[regime].append(True)
        elif outcome in {"miss", "wrong", "loss"}:
            outcomes_by_regime[regime].append(False)

    accuracy = {
        regime: round(sum(vals) / len(vals), 3)
        for regime, vals in outcomes_by_regime.items()
        if vals
    }
    return {
        "total": len(scenarios),
        "by_regime": {r: by_regime.get(r, 0) for r in REGIMES},
        "accuracy": accuracy,
    }
