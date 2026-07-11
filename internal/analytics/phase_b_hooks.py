"""Refresh Agent B trail subscribers (scenario + pump)."""

from __future__ import annotations

from internal.analytics.pump_feed import sync_pump_trail_events
from internal.analytics.scenario_feed import sync_scenario_trail_events


def refresh_agent_b_trails(
    *,
    pump_payload=None,
    scenario_snapshot=None,
) -> dict:
    """Run both trail syncs; returns emitted counts."""
    return {
        "scenario_events": sync_scenario_trail_events(snapshot=scenario_snapshot),
        "pump_events": sync_pump_trail_events(pump_payload=pump_payload),
    }
