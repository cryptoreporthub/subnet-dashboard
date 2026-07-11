"""Five-phase pump ladder (Phase D — Agent A detection engine)."""

from __future__ import annotations

# Ordered ladder: dormant → stirring → accumulating → pumping → cooling
PHASE_ORDER = ("DORMANT", "STIRRING", "ACCUMULATING", "PUMPING", "COOLING")

# Phases assigned by rising score (COOLING is exit-only, not forward ladder).
FORWARD_PHASES = ("DORMANT", "STIRRING", "ACCUMULATING", "PUMPING")

PHASE_INDEX = {name: idx for idx, name in enumerate(PHASE_ORDER)}

# Minimum composite score to *enter* each phase (hysteresis uses separate exit bands).
PHASE_ENTRY_THRESHOLDS = {
    "DORMANT": 0.0,
    "STIRRING": 0.22,
    "ACCUMULATING": 0.42,
    "PUMPING": 0.62,
    "COOLING": 0.30,
}

# Score must drop below this to leave a phase (prevents flapping).
PHASE_EXIT_THRESHOLDS = {
    "STIRRING": 0.15,
    "ACCUMULATING": 0.35,
    "PUMPING": 0.52,
    "COOLING": 0.20,
}

PHASE_LOCK_MINUTES = int(__import__("os").environ.get("PUMP_LADDER_LOCK_MINUTES", "12"))

STATE_PATH = __import__("os").environ.get("PUMP_LADDER_STATE_PATH", "data/pump_ladder.json")

TRAIL_PHASES = {"STIRRING", "ACCUMULATING", "PUMPING", "COOLING"}
